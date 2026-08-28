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

# Nintendo's PRUDP v0 transport uses a 1000-byte MTU and a 962-byte maximum
# logical fragment payload. RMC responses larger than this must be split into
# acknowledged DATA packets. Fragment ids count upward from one; an id of zero
# marks the final fragment (and is also used by an unfragmented message).
PRUDP_FRAGMENT_SIZE = 962

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
    # UserStorage(53) m9 GetContentUrl returns UserContentURL: three Quazal
    # strings (protocol, host, path). The empty form remains useful as a
    # decoder probe; external_content_url builds a usable URL per request.
    "external_content_stub": struct.pack("<HHH", 0, 0, 0),
    "external_content_url": None,
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
PROTO_USER_STORAGE = 53
# 01.06 only. Tournament method 7 is GetJoinedSeason.  The Wager Match menu
# waits for this call to decode successfully; a generic empty body completes
# at the transport layer but leaves the action in its loading state.
PROTO_TOURNAMENT = 105
# 01.06 only. Registered as PatchVersion; see notes/13-v106-port.md. It has
# exactly two methods and blocks the 01.06 boot until method 1 is answered.
#
# NOTE ON NAMING: both builds actually assign 101 to the Monetization protocol
# and 102 to the Shop protocol. PROTO_MONETIZATION above is therefore a
# misnomer for protocol 102 (= Shop); the wire behaviour it implements was
# derived empirically and is correct. The name is kept to avoid churning the
# server, tests, and shipped documentation at once.
PROTO_PATCH_VERSION = 106
# Additional 01.06-only services. Their inactive response bodies below are
# derived from the retail client's response decoders, not guessed qResult
# placeholders. See notes/13-v106-port.md for the parser addresses.
PROTO_LOGIN_REWARD = 107
PROTO_DAILY_POPUP = 108
PROTO_CHALLENGE = 109
PROTO_COMMUNITY_BOSS_FIGHT = 110

# Protocol 106 method 1's client-side decoder reads exactly five u32 fields.
# CheckPatchVersions (0x00278DD8 in 01.06) compares fields 0, 1 and 2 against
# s_application +0x1A08/+0x1A0C/+0x1A10. Live 2026-08-26 those app fields
# were 3, 2, 2 even though the served remote config has no
# SetX360CPTUVersions / SetPS3SCEAPatchVersion / SetPS3SCEEPatchVersion
# keys, so the default body is [3, 2, 2, 0, 0] not zeros.
#
# Override any field live without a code change:
#   P106M1_0=..  P106M1_1=..  P106M1_2=..  P106M1_3=..  P106M1_4=..
PATCH_VERSION_FIELDS = 5
DEFAULT_PATCH_VERSIONS = (3, 2, 2, 0, 0)

# UserStorage is still being probed method-by-method.  Keep the two response
# shapes currently understood out of the "unknown" diagnostic, but capture
# every request so a future method cannot be lost in the generic fallback.
USERSTORAGE_KNOWN_METHODS = frozenset((1, 6, 7, 8, 9, 21))

# ContentProperty 100 selects the title's native payload apply routine. These
# are the exact Variant::I64 values captured in each title's method-6 upload
# request, so enumeration must replay the map for the running title version.
USER_CONTENT_FORMAT_VERSIONS_BY_TITLE = {
    "01.00": {
        0x80000001: 2,
        0x80000002: 1,
        0x80000003: 2,
    },
    "01.06": {
        0x80000001: 5,
        0x80000002: 2,
        0x80000003: 4,
    },
}
# Retain the historical name for callers that explicitly mean the 01.00 map.
USER_CONTENT_FORMAT_VERSIONS = USER_CONTENT_FORMAT_VERSIONS_BY_TITLE["01.00"]


def user_content_format_version(type_id, title_version=None):
    if title_version is None:
        title_version = os.environ.get("SPARTACUS_TITLE_VERSION", "01.00")
    formats = USER_CONTENT_FORMAT_VERSIONS_BY_TITLE.get(title_version)
    if formats is None:
        formats = USER_CONTENT_FORMAT_VERSIONS_BY_TITLE["01.00"]
    return formats.get(type_id)

# Response shapes recovered from the client's OWN response parser (parser
# 0x00018C4C, 15 methods - see notes/05-monetization-method-map.md).  Methods
# that share a parser case body share a response shape, which is why only a
# handful of distinct shapes cover all 15 methods.  Verified against every
# live-validated method: m3 list, m6/m11 two-u32, m7 two-u32 + 16-byte receipt,
# m12 void.  Used as the informed default for methods we do not implement yet,
# so an unhandled shop call is answered in the shape its parser expects.
P102_METHOD_SHAPES = {
    # case body 0x00018E24 - two u32 (the gold/silver balance pair), shared with
    # the implemented m6/m11/m13.
    5: "balances",
    # case body 0x00018EBC - exactly one u32, read into output slot 0 (or
    # consumed and discarded when the caller passes no slot). Methods 14/15
    # are live-validated gold responses. Method 9 is handled explicitly below:
    # a fight with an equipped boost proved it consumes one use and returns the
    # remaining count.
    14: "gold",
    15: "gold",
    # case body 0x00019010 - a list built with the same list decoder as m3
    # (0x004CEAC0); a u32 count of 0 is a structurally correct empty list.
    2: "zero",
    # Methods 1 (0x004CF094), 4 (0x00015D88) and 8 (0x004CE5B8 + u64) decode
    # structured objects whose layout is not yet recovered.  They keep the
    # default receipt so the reply is never shorter than the parser expects;
    # capture them live before implementing.
}
STORE_REFRESH_SENTINEL = 99999
SLOT_ENTITLEMENT_MIN = 80002
SLOT_ENTITLEMENT_MAX = 80007
CONSUMABLE_ITEM_ID_MIN = 60000
CONSUMABLE_ITEM_ID_MAX = 60063
# Runtime v1.06 Boost catalog prices captured before any Shop-method-3 merge.
# Tuples are (gold, silver). Some silver-priced boosts retain an ignored
# one-gold value in the catalog; preserving both words matches the client data.
V106_CONSUMABLE_RETAIL_PRICES = {
    60000: (0, 0),
    60001: (10, 0), 60002: (10, 0), 60003: (10, 0),
    60004: (12, 0), 60005: (10, 0), 60006: (20, 0), 60007: (20, 0),
    60008: (1, 500), 60009: (3, 0),
    60010: (1, 500), 60011: (3, 0),
    60012: (1, 500), 60013: (3, 0),
    60014: (1, 500), 60015: (3, 0),
    60016: (1, 500), 60017: (3, 0),
    60018: (1, 500), 60019: (3, 0),
    60020: (1, 500), 60021: (3, 0),
    60022: (1, 500), 60023: (3, 0),
}
# Retail Face Carver grants one five-use stack. Other consumable stack sizes
# remain unknown and retain the legacy one-unit fallback until verified.
CONSUMABLE_STACK_USES = {60020: 5}
PROTO_NAMES = {0x0A: "TicketGranting", 0x0B: "SecureConnection",
               0x0E: "GlobalNotificationEvent", 102: "Monetization",
               105: "Tournament", 106: "PatchVersion",
               107: "LoginReward", 108: "DailyPopup",
               109: "Challenge", 110: "CommunityBossFight"}


class EconomyStore:
    """Small atomic JSON store for the title's server-side economy."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.lock = threading.RLock()
        # Confirmed clean post-tutorial economy. Existing JSON profiles always
        # override these values, so upgrades preserve their current balances.
        self.data = {
            "version": 1,
            "gold": 0,
            "silver": 200,
            "fame": 0,
            "owned_items": [],
            "item_quantities": {},
            "claimed_challenges": [],
            "daily_challenges": {"date": "", "claimed": []},
            "daily_login": {
                "last_login_date": "",
                "rewards": [],
                "schedule": [],
            },
        }
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.data["gold"] = max(0, int(loaded.get("gold", 0)))
            self.data["silver"] = max(0, int(loaded.get("silver", 0)))
            # Fame was not stored by releases before the 01.06 Shop method-20
            # path was recovered. Missing values migrate safely from zero.
            self.data["fame"] = max(0, int(loaded.get("fame", 0)))
            # Older server builds treated the recruitment-store refresh
            # command (99999) as a normal item purchase.  It is not an item
            # and must never be returned by RequestInventory.
            self.data["owned_items"] = sorted({
                int(item) & 0xFFFFFFFF
                for item in loaded.get("owned_items", [])
                if (int(item) & 0xFFFFFFFF) != STORE_REFRESH_SENTINEL
            })
            loaded_quantities = loaded.get("item_quantities", {})
            if not isinstance(loaded_quantities, dict):
                loaded_quantities = {}
            owned_items = set(self.data["owned_items"])
            quantities = {}
            for item, quantity in loaded_quantities.items():
                try:
                    item = int(item) & 0xFFFFFFFF
                    quantity = max(0, min(99, int(quantity)))
                except (TypeError, ValueError):
                    continue
                if item in owned_items:
                    quantities[item] = quantity
            self.data["item_quantities"] = quantities
            self.data["claimed_challenges"] = sorted({
                int(challenge_id)
                for challenge_id in loaded.get("claimed_challenges", [])
                if 1 <= int(challenge_id) <= 72
            })
            daily = loaded.get("daily_challenges", {})
            if not isinstance(daily, dict):
                daily = {}
            daily_date = str(daily.get("date", ""))
            daily_claimed = sorted({
                int(challenge_id)
                for challenge_id in daily.get("claimed", [])
                if 52 <= int(challenge_id) <= 72
            })
            self.data["daily_challenges"] = {
                "date": daily_date,
                "claimed": daily_claimed,
            }
            daily_login = loaded.get("daily_login", {})
            if not isinstance(daily_login, dict):
                daily_login = {}
            login_rewards = []
            for reward in daily_login.get("rewards", []):
                try:
                    candidate = tuple(int(value) for value in reward)
                except (TypeError, ValueError):
                    continue
                if len(candidate) != 6:
                    continue
                stage = candidate[0]
                if candidate in V106_DAILY_LOGIN_REWARDS.get(stage, ()):
                    login_rewards.append(list(candidate))
            # A valid stash is an ordered prefix of the seven retail stages.
            if [reward[0] for reward in login_rewards] != \
                    list(range(1, len(login_rewards) + 1)):
                login_rewards = []
            login_schedule = []
            for reward in daily_login.get("schedule", []):
                try:
                    candidate = tuple(int(value) for value in reward)
                except (TypeError, ValueError):
                    continue
                if len(candidate) != 6:
                    continue
                stage = candidate[0]
                if candidate in V106_DAILY_LOGIN_REWARDS.get(stage, ()):
                    login_schedule.append(list(candidate))
            if [reward[0] for reward in login_schedule] != list(range(1, 8)):
                login_schedule = []
            # Profiles written by the first experimental build have a stash
            # but no seven-stage schedule. Reconstruct one deterministically
            # while retaining every already-selected earned reward.
            if login_rewards and not login_schedule:
                try:
                    seed_date = datetime.date.fromisoformat(str(
                        daily_login.get("last_login_date", "")
                    ))
                except ValueError:
                    seed_date = datetime.date(1970, 1, 1)
                login_schedule = self._daily_login_schedule(seed_date)
                login_schedule[:len(login_rewards)] = login_rewards
            self.data["daily_login"] = {
                "last_login_date": str(
                    daily_login.get("last_login_date", "")
                ),
                "rewards": login_rewards,
                "schedule": login_schedule,
            }
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

    def add_rewards(self, gold_delta, silver_delta, fame_delta):
        """Atomically apply the three reward currencies used by 01.06."""
        with self.lock:
            self.data["gold"] = max(0, self.data["gold"] + gold_delta)
            self.data["silver"] = max(0, self.data["silver"] + silver_delta)
            self.data["fame"] = max(0, self.data["fame"] + fame_delta)
            self._save()
            return (
                self.data["gold"],
                self.data["silver"],
                self.data["fame"],
            )

    def purchase(self, item_id, gold_cost, silver_cost):
        with self.lock:
            owned = set(self.data["owned_items"])
            consumable_uses = CONSUMABLE_STACK_USES.get(item_id)
            if item_id not in owned or consumable_uses is not None:
                if gold_cost >= 0:
                    self.data["gold"] = max(0, self.data["gold"] - gold_cost)
                if silver_cost >= 0:
                    self.data["silver"] = max(0, self.data["silver"] - silver_cost)
                previous_quantity = (
                    self.item_quantity(item_id) if item_id in owned else 0
                )
                owned.add(item_id)
                self.data["owned_items"] = sorted(owned)
                self.data["item_quantities"][item_id] = min(
                    99, previous_quantity + (consumable_uses or 1)
                )
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

    def item_quantity(self, item_id):
        """Return a consumable's persisted uses with a legacy-safe fallback."""
        with self.lock:
            if item_id not in set(self.data["owned_items"]):
                return 0
            return self.data["item_quantities"].get(
                item_id, CONSUMABLE_STACK_USES.get(item_id, 1)
            )

    def consume_item(self, item_id):
        """Consume one use and atomically persist the remaining count."""
        with self.lock:
            remaining = max(0, self.item_quantity(item_id) - 1)
            if item_id in set(self.data["owned_items"]):
                self.data["item_quantities"][item_id] = remaining
                self._save()
            return remaining

    def slot_entitlements(self):
        """Return the persisted purchases that unlock Ludus roster slots."""
        with self.lock:
            return [
                item for item in self.data["owned_items"]
                if SLOT_ENTITLEMENT_MIN <= item <= SLOT_ENTITLEMENT_MAX
            ]

    def method_8_transactions(self):
        """Return the complete purchase/quantity snapshot replayed at login.

        Method 7 makes a purchase visible immediately, but that client state is
        volatile. Method 8 reconstructs the purchase history on a cold boot:
        permanent equipment, perks and slot entitlements are idempotent
        quantity-one records, while consumables carry their persisted
        remaining-use count. Zero-count consumables have no positive state to
        seed and are omitted.
        """
        with self.lock:
            owned = set(self.data["owned_items"])
            transactions = []
            for item in sorted(owned):
                if CONSUMABLE_ITEM_ID_MIN <= item <= CONSUMABLE_ITEM_ID_MAX:
                    quantity = self.item_quantity(item)
                    if quantity > 0:
                        transactions.append((item, quantity))
                else:
                    transactions.append((item, 1))
            return transactions

    def claim_challenge_reward(self, reward, daily=False, claim_date=None):
        """Credit one retail challenge reward exactly once per claim scope."""
        if claim_date is None:
            claim_date = datetime.datetime.now(datetime.timezone.utc).date()
        claim_date = claim_date.isoformat()
        challenge_id, item_id, quantity, silver, gold, fame = reward
        with self.lock:
            if daily:
                state = self.data["daily_challenges"]
                if state["date"] != claim_date:
                    state = {"date": claim_date, "claimed": []}
                    self.data["daily_challenges"] = state
                claimed = set(state["claimed"])
            else:
                claimed = set(self.data["claimed_challenges"])

            if challenge_id in claimed:
                return False

            self.data["gold"] = max(0, self.data["gold"] + gold)
            self.data["silver"] = max(0, self.data["silver"] + silver)
            self.data["fame"] = max(0, self.data["fame"] + fame)
            if item_id and quantity:
                owned = set(self.data["owned_items"])
                owned.add(item_id)
                self.data["owned_items"] = sorted(owned)
            claimed.add(challenge_id)
            if daily:
                self.data["daily_challenges"]["claimed"] = sorted(claimed)
            else:
                self.data["claimed_challenges"] = sorted(claimed)
            self._save()
            return True

    def completed_challenges(self, daily=False, claim_date=None):
        """Return permanent claims or today's resettable daily claims."""
        if claim_date is None:
            claim_date = datetime.datetime.now(datetime.timezone.utc).date()
        claim_date = claim_date.isoformat()
        with self.lock:
            if not daily:
                return list(self.data["claimed_challenges"])
            state = self.data["daily_challenges"]
            if state["date"] != claim_date:
                self.data["daily_challenges"] = {
                    "date": claim_date,
                    "claimed": [],
                }
                self._save()
                return []
            return list(state["claimed"])

    def register_daily_login(self, login_date=None):
        """Add at most one retail daily-login stage for a UTC date."""
        if login_date is None:
            login_date = datetime.datetime.now(datetime.timezone.utc).date()
        login_date_text = login_date.isoformat()
        with self.lock:
            state = self.data["daily_login"]
            if state["last_login_date"] == login_date_text:
                return False
            rewards = state["rewards"]
            next_stage = len(rewards) + 1
            if next_stage > len(V106_DAILY_LOGIN_REWARDS):
                return False
            if not state["schedule"]:
                state["schedule"] = self._daily_login_schedule(login_date)
            reward = tuple(state["schedule"][next_stage - 1])
            rewards.append(list(reward))
            state["last_login_date"] = login_date_text
            self._save()
            return True

    @staticmethod
    def _daily_login_schedule(seed_date):
        """Choose and return one complete seven-stage retail reward cycle."""
        schedule = []
        for stage in range(1, 8):
            alternatives = V106_DAILY_LOGIN_REWARDS[stage]
            # Only stage 2 currently has alternatives. The stable cycle seed
            # keeps its advertised item identical on every info read.
            selected = alternatives[
                seed_date.toordinal() % len(alternatives)
            ]
            schedule.append(list(selected))
        return schedule

    def daily_login_rewards(self):
        """Return the currently accumulated, unclaimed login-reward stash."""
        with self.lock:
            return [tuple(reward) for reward in self.data["daily_login"]["rewards"]]

    def daily_login_info(self, now=None):
        """Return the schedule, current stage index, and UTC reset countdown.

        The 01.06 client uses the first u32 as the zero-based highlighted
        reward index.  It multiplies the second u32 by 1000 and clamps it to
        86,400 seconds before starting its next-login timer.
        """
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        else:
            now = now.astimezone(datetime.timezone.utc)
        tomorrow = datetime.datetime.combine(
            now.date() + datetime.timedelta(days=1),
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        seconds_until_reset = max(
            1, min(86400, int((tomorrow - now).total_seconds()))
        )
        with self.lock:
            schedule = [
                tuple(reward)
                for reward in self.data["daily_login"]["schedule"]
            ]
            earned_count = len(self.data["daily_login"]["rewards"])
        current_stage_index = max(0, earned_count - 1)
        return schedule, current_stage_index, seconds_until_reset

    def claim_daily_login_rewards(self):
        """Credit and clear the accumulated login rewards atomically."""
        with self.lock:
            rewards = [
                tuple(reward)
                for reward in self.data["daily_login"]["rewards"]
            ]
            if not rewards:
                return []
            owned = set(self.data["owned_items"])
            for _stage, item_id, quantity, silver, gold, fame in rewards:
                self.data["gold"] = max(0, self.data["gold"] + gold)
                self.data["silver"] = max(0, self.data["silver"] + silver)
                self.data["fame"] = max(0, self.data["fame"] + fame)
                if item_id and quantity:
                    owned.add(item_id)
                    added = quantity * CONSUMABLE_STACK_USES.get(item_id, 1)
                    current = self.data["item_quantities"].get(item_id, 0)
                    self.data["item_quantities"][item_id] = min(
                        99, current + added
                    )
            self.data["owned_items"] = sorted(owned)
            self.data["daily_login"]["rewards"] = []
            self.data["daily_login"]["schedule"] = []
            self._save()
            return rewards


INVENTORY_PROBE = os.environ.get(
    "SPARTACUS_INVENTORY_PROBE", ""
) not in ("", "0")


def parse_inventory_price_probe(value):
    """Parse diagnostic ``item:gold:silver`` rows from an environment value."""
    result = {}
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            raise ValueError(
                "SPARTACUS_INVENTORY_PRICE_PROBE entries must be "
                "item:gold:silver"
            )
        item_id, gold, silver = (int(part, 0) for part in parts)
        if not 0 <= item_id <= 0xFFFFFFFF \
                or not 0 <= silver <= 0xFFFFFFFF \
                or not 0 <= gold <= 0xFFFFFFFF:
            raise ValueError("inventory price probe values must be u32")
        result[item_id] = (gold, silver)
    return result


INVENTORY_PRICE_PROBE = parse_inventory_price_probe(os.environ.get(
    "SPARTACUS_INVENTORY_PRICE_PROBE", ""
))
DAILY_LOGIN_REWARDS_ENABLED = os.environ.get(
    "SPARTACUS_DAILY_LOGIN_REWARDS", ""
) not in ("", "0")

# Diagnostic-only Method 3 records for three known-owned weapons.  Keeping
# the price/count fields at zero isolates the two boolean fields and their
# possible interaction in a single cold boot.
INVENTORY_PROBE_FIELDS = {
    10236: (0, True,  0, 0, False, 0, 0),  # boolean field 4 only
    10250: (0, False, 0, 0, True,  0, 0),  # boolean field 7 only
    10265: (0, True,  0, 0, True,  0, 0),  # both boolean fields
    # The first live probe made the equipped boost recognizable but depleted.
    # Method 10 was not called, so that state came entirely from this record.
    # Keep the accepted entitlement fields and isolate the final u32 as the
    # remaining-count candidate.
    60020: (1, True, 0, 0, False, 1, 1),
}


def inventory_item_fields(item_id, title_version=None):
    if item_id in INVENTORY_PRICE_PROBE:
        gold, silver = INVENTORY_PRICE_PROBE[item_id]
        # A/B are left unowned; C/D are the ordinary comparison price and
        # E=false keeps the optional F/G sale pair inactive.
        return (0, False, gold, silver, False, 0, 0)
    if INVENTORY_PROBE and item_id in INVENTORY_PROBE_FIELDS:
        return INVENTORY_PROBE_FIELDS[item_id]
    if title_version is None:
        title_version = os.environ.get("SPARTACUS_TITLE_VERSION", "01.00")
    if title_version == "01.06" \
            and item_id in V106_CONSUMABLE_RETAIL_PRICES:
        gold, silver = V106_CONSUMABLE_RETAIL_PRICES[item_id]
        return (0, False, gold, silver, False, 0, 0)
    return (0, False, 0, 0, False, 1, 0)


def encode_inventory_item(item_id, title_version=None):
    """Encode the 9 fields read by Monetization method 3's item decoder."""
    return (struct.pack("<I", item_id)
            + struct.pack("<H", 1) + b"\x00"  # empty Quazal string
            # A/B carry still-partial inventory state. C/D are ordinary
            # gold/silver prices; E selects optional sale prices F/G.
            + struct.pack("<I?II?II",
                          *inventory_item_fields(item_id, title_version)))


def encode_inventory(items, title_version=None):
    return struct.pack("<I", len(items)) + b"".join(
        encode_inventory_item(item, title_version) for item in items
    )


def method_3_inventory_items(items, title_version=None):
    """Return owned IDs whose ownership metadata method 3 should advertise.

    In 01.06 the still-partial A/B ownership fields can corrupt an owned
    consumable's refill state. Method 8 already restores both ownership and
    remaining uses, so owned consumables stay omitted here. Separate unowned
    offer metadata is added by ``method_3_response_items``.

    Keep 01.00 unchanged until the same merge behavior is established there.
    """
    if title_version is None:
        title_version = os.environ.get("SPARTACUS_TITLE_VERSION", "01.00")
    if title_version != "01.06":
        return list(items)
    return [
        item for item in items
        if not CONSUMABLE_ITEM_ID_MIN <= item <= CONSUMABLE_ITEM_ID_MAX
    ]


def method_3_response_items(requested, owned, title_version=None,
                            price_probe=None):
    """Select owned rows and v1.06 metadata rows in request order.

    Method 8 remains authoritative for v1.06 Boost ownership and remaining
    uses. Method 3 independently supplies ordinary-price metadata for every
    requested Boost; its A/B fields do not disturb the method-8 quantity.
    Omitting either owned or unowned Boosts leaves their original/comparison
    price zero-initialized and incorrectly renders those cards on sale.
    """
    if title_version is None:
        title_version = os.environ.get("SPARTACUS_TITLE_VERSION", "01.00")
    selected = set(method_3_inventory_items(
        owned, title_version=title_version
    ))
    owned = set(owned)
    if title_version == "01.06":
        selected.update(
            item_id for item_id in requested
            if item_id in V106_CONSUMABLE_RETAIL_PRICES
        )
    if price_probe is None:
        price_probe = INVENTORY_PRICE_PROBE
    selected.update(item_id for item_id in requested if item_id in price_probe)
    result = []
    for item_id in requested:
        if item_id in selected and item_id not in result:
            result.append(item_id)
    return result


def encode_qdatetime(value=None):
    """Pack the title's zero-based-month/day Quazal date/time in UTC."""
    if value is None:
        value = datetime.datetime.now(datetime.timezone.utc)
    return (
        ((value.year & 0x3FFF) << 26)
        | (((value.month - 1) & 0x0F) << 22)
        | (((value.day - 1) & 0x1F) << 17)
        | ((value.hour & 0x1F) << 12)
        | ((value.minute & 0x3F) << 6)
        | (value.second & 0x3F)
    )


def encode_no_joined_tournament_season():
    """Encode Tournament.GetJoinedSeason's valid "not joined" result.

    The 01.06 response decoder at 0x000492F8 reads, in order: a u32 season
    identifier, a Quazal string, two u64 date/times, three u32 fields, and a
    list count. Quazal strings include their trailing NUL in the u16 length,
    so an empty string is ``<u16 1, NUL>`` rather than ``<u16 0>``.
    """
    return (
        struct.pack("<IH", 0, 1)
        + b"\x00"
        + struct.pack("<QQIIII", 0, 0, 0, 0, 0, 0)
    )


V106_CHALLENGE_REWARDS = {
    # All 72 exact rows from retail 01.06 XML.dat's challenge_reward table:
    # id, item_id, item_quantity, silver, gold, fame.
    1: (1, 0, 0, 1000, 0, 0),
    2: (2, 0, 0, 2000, 0, 2000),
    3: (3, 130078, 1, 4000, 10, 4000),
    4: (4, 0, 0, 1000, 0, 0),
    5: (5, 0, 0, 2000, 0, 2000),
    6: (6, 130073, 1, 4000, 10, 4000),
    7: (7, 0, 0, 1000, 0, 0),
    8: (8, 0, 0, 2000, 0, 2000),
    9: (9, 130031, 1, 4000, 20, 4000),
    10: (10, 0, 0, 1000, 0, 0),
    11: (11, 0, 0, 2000, 0, 2000),
    12: (12, 130011, 1, 4000, 10, 4000),
    13: (13, 0, 0, 2500, 0, 0),
    14: (14, 0, 0, 5000, 2, 2000),
    15: (15, 130060, 1, 10000, 5, 4000),
    16: (16, 0, 0, 2500, 0, 0),
    17: (17, 0, 0, 5000, 2, 2000),
    18: (18, 130020, 1, 10000, 5, 4000),
    19: (19, 0, 0, 1000, 0, 0),
    20: (20, 0, 0, 2000, 0, 2000),
    21: (21, 0, 0, 4000, 40, 4000),
    22: (22, 0, 0, 1000, 0, 0),
    23: (23, 0, 0, 2000, 0, 2000),
    24: (24, 0, 0, 4000, 40, 4000),
    25: (25, 0, 0, 1000, 0, 0),
    26: (26, 0, 0, 2000, 0, 2000),
    27: (27, 0, 0, 4000, 40, 4000),
    28: (28, 0, 0, 1000, 0, 0),
    29: (29, 0, 0, 2000, 0, 2000),
    30: (30, 0, 0, 4000, 40, 4000),
    31: (31, 0, 0, 1000, 0, 0),
    32: (32, 0, 0, 2000, 0, 2000),
    33: (33, 0, 0, 4000, 40, 4000),
    34: (34, 0, 0, 1000, 0, 0),
    35: (35, 0, 0, 2000, 0, 2000),
    36: (36, 0, 0, 4000, 40, 4000),
    37: (37, 0, 0, 1000, 0, 0),
    38: (38, 0, 0, 2000, 0, 2000),
    39: (39, 0, 0, 4000, 40, 4000),
    40: (40, 0, 0, 1000, 0, 0),
    41: (41, 0, 0, 2000, 0, 2000),
    42: (42, 0, 0, 4000, 40, 4000),
    43: (43, 0, 0, 2000, 0, 0),
    44: (44, 0, 0, 4000, 0, 1000),
    45: (45, 130051, 1, 5000, 0, 1000),
    46: (46, 0, 0, 0, 1, 0),
    47: (47, 0, 0, 0, 2, 1000),
    48: (48, 130033, 1, 0, 5, 1000),
    49: (49, 0, 0, 0, 1, 0),
    50: (50, 0, 0, 0, 2, 1000),
    51: (51, 130072, 1, 0, 5, 1000),
    52: (52, 0, 0, 2000, 0, 2000),
    53: (53, 0, 0, 4000, 0, 4000),
    54: (54, 0, 0, 8000, 0, 8000),
    55: (55, 0, 0, 1000, 0, 1000),
    56: (56, 0, 0, 2000, 0, 2000),
    57: (57, 0, 0, 4000, 0, 4000),
    58: (58, 60009, 1, 0, 0, 500),
    59: (59, 0, 0, 0, 1, 1000),
    60: (60, 60006, 1, 0, 0, 2000),
    61: (61, 0, 0, 500, 0, 500),
    62: (62, 0, 0, 1000, 0, 1000),
    63: (63, 60006, 1, 0, 0, 2000),
    64: (64, 0, 0, 1000, 0, 1000),
    65: (65, 0, 0, 2000, 0, 2000),
    66: (66, 60006, 1, 0, 0, 4000),
    67: (67, 60010, 1, 0, 0, 500),
    68: (68, 60012, 1, 0, 0, 1000),
    69: (69, 60014, 1, 0, 0, 2000),
    70: (70, 60007, 1, 0, 0, 1000),
    71: (71, 60007, 1, 0, 0, 2000),
    72: (72, 60007, 1, 0, 0, 4000),
}
V106_DAILY_CHALLENGE_IDS = frozenset(range(52, 73))

# Retail 01.06 XML.dat DailyLogin_RewardSets rows.  The tuple order matches
# the source table used by V106_CHALLENGE_REWARDS:
#   stage, item_id, item_quantity, silver, gold, fame.
# Stage 2 has eight equally weighted alternatives; a particular selection is
# persisted when that stage is first granted so repeated reads cannot change
# the pending reward.
V106_DAILY_LOGIN_REWARDS = {
    1: ((1, 0, 0, 300, 0, 0),),
    2: tuple(
        (2, item_id, 1, 0, 0, 0)
        for item_id in (60008, 60010, 60012, 60014,
                        60016, 60018, 60020, 60022)
    ),
    3: ((3, 0, 0, 700, 0, 0),),
    4: ((4, 60006, 1, 0, 0, 0),),
    5: ((5, 0, 0, 2000, 0, 0),),
    6: ((6, 120051, 1, 0, 0, 0),),
    7: ((7, 0, 0, 0, 10, 0),),
}


def encode_v106_challenge_reward(reward):
    """Encode a retail challenge-reward DB row in the 01.06 RPC order.

    The XML source row is ``id, item_id, item_quantity, silver, gold, fame``.
    The shared six-u32 reward DTO follows the XML reward presentation columns:
    ``id, gold, silver, fame, item_id, item_quantity``.  A live claim made the
    distinction observable: placing silver in DTO slot 3 increased displayed
    fame while leaving displayed silver unchanged.
    """
    reward_id, item_id, item_quantity, silver, gold, fame = reward
    return struct.pack(
        "<6I", reward_id, gold, silver, fame, item_id, item_quantity
    )


def encode_v106_daily_login_reward(reward):
    """Encode a retail Daily Login row in LoginReward's native order.

    Unlike Challenge's superficially similar six-u32 DTO, LoginReward keeps
    the XML/database order on the wire: ``stage, item_id, item_quantity,
    silver, gold, fame``.  The 01.06 claim callback at 0x00068EC8 reads those
    exact offsets when applying the reward to the live economy.
    """
    return struct.pack("<6I", *reward)


def encode_v106_daily_login_reward_list(rewards):
    """Encode LoginReward's list of six-u32 Daily Login records."""
    return struct.pack("<I", len(rewards)) + b"".join(
        encode_v106_daily_login_reward(reward) for reward in rewards
    )


def encode_v106_protocol_response(protocol, method, params=b"", now=None):
    """Return an exact, statically proven 01.06 protocol response body.

    ``None`` means that the method's complete layout or inactive semantics are
    not yet proven and the caller must continue to the diagnostic fallback.
    Explicit ``P<n>M<n>`` overrides remain authoritative at dispatch time.
    """
    if protocol == PROTO_TOURNAMENT:
        if method == 2:
            # Helper 0x0004893C: u32, bool, two u64 date/times, u32,
            # then two independent list counts.
            return struct.pack("<I?QQIII", 0, False, 0, 0, 0, 0, 0)
        if method == 5:
            # Helper 0x00049D68: one u32 followed by a list count.
            return struct.pack("<II", 0, 0)
        if method == 14:
            # Parser 0x00047C6C calls list decoder 0x005529AC twice.
            return struct.pack("<II", 0, 0)

    if protocol == PROTO_LOGIN_REWARD:
        if method == 1:
            # DailyLogin request stub 0x00034868 writes u32 + bool; its
            # response parser reads one serialized bool.
            return struct.pack("<?", False)
        if method == 2:
            # GetDailyLoginInfo: list<Daily Login six-u32 record>, u32, u32.
            return struct.pack("<III", 0, 0, 0)
        if method == 3:
            # GetDailyLoginInfoEx: list<Daily Login six-u32 record>, u32, u32,
            # Quazal DateTime. Request stub 0x00033B3C has no input fields.
            return struct.pack("<IIIQ", 0, 0, 0, encode_qdatetime(now))
        if method == 4:
            # ClaimLoginRewards request stub 0x00032E48 writes one u32 and
            # receives a list of Daily Login six-u32 records.
            return struct.pack("<I", 0)

    if protocol == PROTO_DAILY_POPUP and method == 1:
        # Parser 0x00026A1C: bool, then helper 0x0002710C's
        # u32/bool/bool tuple, followed by a list count.
        return struct.pack("<?I??I", False, 0, False, False, 0)

    if protocol == PROTO_CHALLENGE:
        if method in (1, 3):
            # ClaimChallengeReward is player PID + challenge ID. The live
            # ClaimDailyChallengeReward request is challenge ID + qDateTime.
            # Both responses use the same six-u32 DTO decoded by 0x0001E018.
            try:
                challenge_id = struct.unpack_from(
                    "<I", params, 4 if method == 1 else 0
                )[0]
            except struct.error:
                challenge_id = 0
            row = V106_CHALLENGE_REWARDS.get(
                challenge_id, (0, 0, 0, 0, 0, 0)
            )
            return encode_v106_challenge_reward(row)
        if method in (2, 4):
            # List decoder 0x00546B58 reads a count then one u32 per element.
            return struct.pack("<I", 0)

    if protocol == PROTO_COMMUNITY_BOSS_FIGHT and method in (1, 5):
        # Both cases call list decoder 0x00547D74.
        return struct.pack("<I", 0)

    return None


def encode_purchase_result(gold, silver, item_id, transaction_time=0, quantity=1):
    """Encode method 7/13 balances and its 16-byte transaction receipt."""
    return struct.pack(
        "<IIIQI", gold, silver, item_id, transaction_time, quantity
    )


def decode_recruit_request(params, title_version=None):
    """Decode Shop method 13 for the selected title version.

    01.06 inserts a category u32 before the unchanged signed gold/silver cost
    pair. Both layouts are pinned to live wire captures.
    """
    if title_version is None:
        title_version = os.environ.get("SPARTACUS_TITLE_VERSION", "01.00")
    if title_version == "01.06":
        return struct.unpack_from("<IIIii", params, 0)
    gladiator_id, unknown, gold_cost, silver_cost = struct.unpack_from(
        "<IIii", params, 0
    )
    return gladiator_id, unknown, None, gold_cost, silver_cost


def encode_reward_balances(gold, silver, fame):
    """Encode Shop method 20's three absolute post-reward balances."""
    return struct.pack("<III", gold, silver, fame)


V106_ROSTER_TYPE_ID = 0x80000003
V106_ROSTER_OWNED_COUNT_OFFSET = 0x53B4
V106_ROSTER_FIRST_OWNED_OFFSET = 0x0810
V106_ROSTER_RECORD_STRIDE = 0x0158
V106_ROSTER_OWNED_KEY_OFFSET = 0x08
V106_ROSTER_OWNED_ACTIVE_OFFSET = 0x13C
# The fixed record arrays end immediately before the six-word trailer.  This
# also gives us a format-derived upper bound instead of trusting a corrupt
# count from disk.
V106_ROSTER_TRAILER_OFFSET = 0x53B0
V106_ROSTER_MAX_OWNED = (
    (V106_ROSTER_TRAILER_OFFSET - 4
     - (V106_ROSTER_FIRST_OWNED_OFFSET + V106_ROSTER_OWNED_KEY_OFFSET))
    // V106_ROSTER_RECORD_STRIDE
) + 1


def read_v106_owned_gladiator_records(content_id=1):
    """Read Shop ownership records from the authoritative v1.06 type-3 save.

    The v1.06 format-4 converter copies each old-format owned record from
    file +0x810 to manager +0x820.  Its owned count is the big-endian u32 at
    +0x53B4, and the post-load validator compares record +0x08 against Shop
    method 24's first u32.  Return no records when the file is absent or fails
    structural bounds checks; never infer ownership from partial data.
    """
    try:
        with open(user_content_path(V106_ROSTER_TYPE_ID, content_id), "rb") as f:
            payload = f.read()
    except OSError:
        return ()

    if len(payload) < V106_ROSTER_OWNED_COUNT_OFFSET + 4:
        return ()
    owned_count = struct.unpack_from(
        ">I", payload, V106_ROSTER_OWNED_COUNT_OFFSET
    )[0]
    if owned_count > V106_ROSTER_MAX_OWNED:
        return ()

    records = []
    for index in range(owned_count):
        record_offset = (
            V106_ROSTER_FIRST_OWNED_OFFSET
            + index * V106_ROSTER_RECORD_STRIDE
        )
        key_offset = record_offset + V106_ROSTER_OWNED_KEY_OFFSET
        active_offset = record_offset + V106_ROSTER_OWNED_ACTIVE_OFFSET
        if key_offset + 4 > len(payload) or active_offset >= len(payload):
            return ()
        gladiator_id = struct.unpack_from(">I", payload, key_offset)[0]
        if gladiator_id == 0:
            return ()
        # Method 24's bool is copied directly to native record +0x13C. False
        # marks a restored gladiator as requiring revival, so this is persistent
        # roster state rather than optional Shop metadata.
        active = 1 if payload[active_offset] else 0
        records.append((gladiator_id, active))
    return tuple(records)


def encode_shop_records(gladiator_records=()):
    """Encode Shop method 24's structured ownership list.

    The 01.06 decoder at 0x00043CD0 reads four u32 values, one serialized
    bool, and a final u32 for every record.  The roster validator at
    0x0025C730 matches field 1 against native owned-record +0x08 and copies
    field 5 to native record +0x13C. The final zero selects the client's
    explicit default appearance mapping; fields 2-4 are not consumed by the
    roster-application path.
    """
    gladiator_records = tuple(gladiator_records)
    return (
        struct.pack("<I", len(gladiator_records))
        + b"".join(
            struct.pack("<IIIIBI", gladiator_id, 0, 0, 0, active, 0)
            for gladiator_id, active in gladiator_records
        )
    )


def encode_monetization_server_time(value=None, transactions=()):
    """Encode method 8's transaction list and authoritative UTC time."""
    if value is None:
        value = datetime.datetime.now(datetime.timezone.utc)
    # Parser 0x00018F8C first decodes a structured list and then a Quazal
    # DateTime.  The client converts that packed calendar value to its internal
    # epoch before calculating the server/local clock offset.  A Unix timestamp
    # is the right width but the wrong representation and produces an enormous
    # signed offset (and therefore multi-million-hour shop countdowns).
    packed_time = encode_qdatetime(value)
    transactions = tuple(
        (int(transaction[0]), int(transaction[1]))
        if isinstance(transaction, (tuple, list))
        else (int(transaction), 1)
        for transaction in transactions
    )
    return (
        struct.pack("<I", len(transactions))
        + b"".join(
            struct.pack(
                "<IQI",
                item & 0xFFFFFFFF,
                packed_time,
                max(0, min(0xFFFFFFFF, quantity)),
            )
            for item, quantity in transactions
        )
        + struct.pack("<Q", packed_time)
    )


LOG_PATH = os.environ.get(
    "SPARTACUS_PRUDP_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "notes", "prudp_server_log.txt"),
)
_LOG_LOCK = threading.Lock()
_LOG_CONTEXT = threading.local()

USERSTORAGE_CAPTURE_DIR = os.environ.get(
    "SPARTACUS_USERSTORAGE_CAPTURE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", ".build", "userstorage-captures")),
)
USERSTORAGE_CAPTURE_ENABLED = os.environ.get(
    "SPARTACUS_CAPTURE_USERSTORAGE", "1"
) not in ("", "0")
_USERSTORAGE_CAPTURE_LOCK = threading.Lock()
_USERSTORAGE_CAPTURE_COUNTER = 0
# Authentication and secure PRUDP endpoints run in separate ``main`` threads.
# Keep the last non-service player identity by peer host so the secure endpoint
# can label later UserStorage captures.  This server currently hosts one local
# player; service-account logins (for example Tracking) must not overwrite it.
_PLAYER_CONTEXT_BY_HOST = {}
_PLAYER_CONTEXT_LOCK = threading.Lock()


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
    prefix = getattr(_LOG_CONTEXT, "prefix", "prudp")
    line = f"[{ts}] [{prefix}] {msg}"
    with _LOG_LOCK:
        print(line, flush=True)
        with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")


def capture_userstorage_request(rmc, packet_info, peer, session_state=None):
    """Persist one protocol-53 request without changing its dispatch path.

    The binary file is exactly ``rmc['params']`` (no decoding or re-encoding),
    while the JSON sidecar carries enough transport/account context to replay
    or correlate it later.  Capture failures are deliberately diagnostic-only:
    a full disk or unwritable directory must never change a server response.
    Returns the payload path, or ``None`` when capture is disabled/failed.
    """
    if not USERSTORAGE_CAPTURE_ENABLED or not rmc \
            or rmc.get("protocol") != PROTO_USER_STORAGE \
            or not rmc.get("is_request"):
        return None

    global _USERSTORAGE_CAPTURE_COUNTER
    params = bytes(rmc.get("params", b""))
    state = session_state or {}
    username = state.get("account_username")
    account_pid = state.get("account_pid")
    account_tag = username or (
        f"pid{int(account_pid):08x}" if account_pid is not None else "unknown"
    )
    # Keep account text out of the path except for a conservative correlation
    # token; the full value remains in the sidecar for investigation.
    safe_tag = "".join(c if c.isalnum() or c in "._-" else "_"
                       for c in str(account_tag))[:48] or "unknown"
    captured_at = datetime.datetime.now(datetime.timezone.utc)
    stamp = captured_at.strftime("%Y%m%dT%H%M%S%fZ")
    with _USERSTORAGE_CAPTURE_LOCK:
        sequence = _USERSTORAGE_CAPTURE_COUNTER
        _USERSTORAGE_CAPTURE_COUNTER += 1

    stem = (f"{stamp}_{sequence:06d}_{safe_tag}_"
            f"s{int(packet_info.get('session_id', 0)):02x}_"
            f"c{int(rmc.get('call_id', 0)):08x}_"
            f"m{int(rmc.get('method_id', 0)):08x}")
    directory = os.path.abspath(USERSTORAGE_CAPTURE_DIR)
    payload_name = stem + ".bin"
    metadata_name = stem + ".json"
    payload_path = os.path.join(directory, payload_name)
    metadata_path = os.path.join(directory, metadata_name)
    metadata = {
        "captured_at": captured_at.isoformat(),
        "protocol": PROTO_USER_STORAGE,
        "method_id": int(rmc.get("method_id", 0)),
        "call_id": int(rmc.get("call_id", 0)),
        "known_method": int(rmc.get("method_id", 0)) in USERSTORAGE_KNOWN_METHODS,
        "params_length": len(params),
        "params_sha256": hashlib.sha256(params).hexdigest(),
        "payload_file": payload_name,
        "account": {
            "username": username,
            "pid": account_pid,
        },
        "peer": [str(peer[0]), int(peer[1])] if peer else None,
        "transport": {
            "source": int(packet_info.get("source", 0)),
            "destination": int(packet_info.get("destination", 0)),
            "session_id": int(packet_info.get("session_id", 0)),
            "sequence_id": int(packet_info.get("sequence_id", 0)),
            "signature": int(packet_info.get("signature", 0)),
        },
    }
    try:
        os.makedirs(directory, exist_ok=True)
        # Write-and-replace keeps readers from observing a partially written
        # payload or sidecar while a live probe is collecting requests.
        payload_tmp = payload_path + f".{os.getpid()}.tmp"
        metadata_tmp = metadata_path + f".{os.getpid()}.tmp"
        with open(payload_tmp, "wb") as f:
            f.write(params)
            f.flush()
            os.fsync(f.fileno())
        os.replace(payload_tmp, payload_path)
        with open(metadata_tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(metadata, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(metadata_tmp, metadata_path)
        return payload_path
    except OSError as error:
        for temporary in (locals().get("payload_tmp"),
                          locals().get("metadata_tmp")):
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        log(f"   !! UserStorage capture failed ({error})")
        return None


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


def build_data_fragments(source, destination, session_id, sequence_id,
                         signature, payload,
                         fragment_size=PRUDP_FRAGMENT_SIZE,
                         flags=FLAG_NEED_ACK):
    """Build one or more ordered PRUDP DATA packets for an RMC message.

    Compression framing and RC4 encryption are deliberately applied by
    ``build`` to each fragment independently, matching Quazal's payload
    encoder. ``sequence_id`` is the first server sequence number consumed;
    callers must reserve one additional sequence number per returned packet.
    """
    if fragment_size <= 0:
        raise ValueError("fragment_size must be positive")

    chunks = [
        payload[offset:offset + fragment_size]
        for offset in range(0, len(payload), fragment_size)
    ] or [b""]
    packets = []
    for index, chunk in enumerate(chunks):
        fragment_id = 0 if index == len(chunks) - 1 else index + 1
        packets.append(build(
            source, destination, TYPE_DATA,
            flags,
            session_id, (sequence_id + index) & 0xFFFF,
            signature=signature, fragment_id=fragment_id, payload=chunk,
        ))
    return packets


def data_fragment_count(payload, fragment_size=PRUDP_FRAGMENT_SIZE):
    """Return how many sequence ids a fragmented DATA message consumes."""
    if fragment_size <= 0:
        raise ValueError("fragment_size must be positive")
    return max(1, (len(payload) + fragment_size - 1) // fragment_size)


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


def encode_user_content_url(protocol: str, host: str, path: str) -> bytes:
    """Encode UserStorage.UserContentURL(protocol, host, path)."""
    return q_string(protocol) + q_string(host) + q_string(path)


def encode_user_content_upload_result(type_id: int, content_id: int = 1) -> bytes:
    """Encode UserStorage m6's upload URL, assigned ID, and empty header list."""
    host = os.environ.get("SPARTACUS_USER_CONTENT_HOST", "127.0.0.1")
    upload_path = f"/usercontent/{type_id:08x}/{content_id}.bin"
    return (
        encode_user_content_url("http://", host, upload_path)
        + struct.pack("<QI", content_id, 0)
    )


def user_content_path(type_id: int, content_id: int) -> str:
    directory = os.environ.get(
        "SPARTACUS_USER_CONTENT_DIR",
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "data", "usercontent")),
    )
    return os.path.join(directory, f"{type_id:08x}", f"{content_id}.bin")


def encode_user_content_rows(type_id: int, content_id: int = 1,
                             owner_pid: int = USER_PID,
                             format_version: int | None = None) -> bytes:
    """Encode one GetOwnContents row and its native format selector."""
    properties = b""
    property_count = 0
    if format_version is not None:
        # The writer supplies ContentProperty 100 as Variant::I64. The loader
        # copies it into context +0x10 and uses values 1/2 to select its apply
        # routine; an omitted property leaves mode 0 and skips application.
        property_count = 1
        properties = struct.pack("<IBQ", 100, 1, format_version)
    return (
        struct.pack("<IIQII", 1, type_id, content_id, owner_pid,
                    property_count)
        + properties
    )


def encode_user_content_download_url(type_id: int, content_id: int = 1) -> bytes:
    host = os.environ.get("SPARTACUS_USER_CONTENT_HOST", "127.0.0.1")
    path = f"/usercontent/{type_id:08x}/{content_id}.bin"
    return encode_user_content_url("http://", host, path)


def encode_remote_config_content(type_id: int, content_id: int,
                                 owner_pid: int, sha256_hex: str) -> bytes:
    """Encode the Crixus SearchContents row used by remote config.

    Property 101 is the expected uppercase SHA-256 string. Property 5 is the
    nonzero DateTime/u64-style value used by the row-selection gate. Property
    100 is the integer revision copied into the applied remote-config state.
    """
    digest = sha256_hex.upper()
    if len(digest) != 64 or any(c not in "0123456789ABCDEF" for c in digest):
        raise ValueError("remote-config SHA-256 must be 64 hexadecimal digits")
    return (
        struct.pack("<IIQII", 1, type_id, content_id, owner_pid, 3)
        + struct.pack("<IBQ", 5, 5, 1)
        + struct.pack("<IBQ", 100, 1, 1)
        + struct.pack("<IB", 101, 4) + q_string(digest)
    )


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


def encode_patch_version_response() -> tuple[bytes, list[int]]:
    """Protocol 106 method 1 body: five little-endian u32 patch versions.

    Returns (body, fields) so the caller can log exactly what was sent. An
    empty body is NOT equivalent: it starves the client's decoder and leaves
    ActOnServerRequestState() reporting ASYNC_STATUS_NONE, which is the
    observed 01.06 "Updating Game Data" hang.
    """
    fields = [
        int(os.environ.get(f"P106M1_{i}", str(DEFAULT_PATCH_VERSIONS[i])), 0)
        for i in range(PATCH_VERSION_FIELDS)
    ]
    return struct.pack(f"<{PATCH_VERSION_FIELDS}I", *fields), fields


def build_rmc_error(protocol: int, call_id: int, error_code: int) -> bytes:
    """Build a failing RMC response.

    The Quazal failure envelope carries the error code in place of the method
    id and body.  This layout follows the documented Quazal/NEX convention and
    is NOT yet confirmed against this title, so it is only reachable through an
    explicit fallback-shape override, never by default.
    """
    inner = bytes([protocol]) + b"\x00"                    # proto, failure
    inner += struct.pack("<II", error_code, call_id)
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
    # Login is normally received on the auth stream before the secure stream
    # carrying UserStorage traffic is opened. Keep the account context by
    # peer so the next CONNECT can inherit it, then copy it into that exact
    # (peer, source-vport) session state.
    account_context_by_peer = {}
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
            packets = build_data_fragments(
                state["server_port"], state["client_port"],
                state["session"], state["next_seq"], state["signature"],
                rmc_msg, flags=FLAG_RELIABLE | FLAG_NEED_ACK,
            )
            try:
                for pkt in packets:
                    srv.sendto(pkt, state["addr"])
                log(f"-> PUSH GlobalNotificationEvent(14) method=1 "
                    f"call={state['next_call']} seq={state['next_seq']} "
                    f"({len(packets)} fragment(s), rmc={len(rmc_msg)}B)")
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
                account_context = account_context_by_peer.get(addr)
                if not account_context:
                    with _PLAYER_CONTEXT_LOCK:
                        account_context = dict(
                            _PLAYER_CONTEXT_BY_HOST.get(addr[0], {})
                        )
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
                        "account_username": account_context.get("username"),
                        "account_pid": account_context.get("pid"),
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

                # Preserve UserStorage inputs only after the transport ACK is
                # on the wire, so filesystem latency cannot perturb the client.
                if rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_USER_STORAGE:
                    capture_key = (addr, info["source"])
                    with state_lock:
                        capture_state = dict(
                            connection_state.get(capture_key, {})
                        )
                    capture_path = capture_userstorage_request(
                        rmc, info, addr, capture_state
                    )
                    kind = ("known" if rmc["method_id"] in
                            USERSTORAGE_KNOWN_METHODS else "UNKNOWN")
                    if capture_path:
                        log(f"   *** UserStorage {kind} method="
                            f"{rmc['method_id']} raw params preserved "
                            f"({len(rmc['params'])}B) -> {capture_path} ***")
                    elif rmc["method_id"] not in USERSTORAGE_KNOWN_METHODS:
                        log(f"   *** UserStorage UNKNOWN method="
                            f"{rmc['method_id']} raw params="
                            f"{rmc['params'].hex()} (capture disabled/failed) ***")

                resp_body = None
                resp_error = None
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
                        username_text = username.decode("utf-8", "replace")
                        account_context_by_peer[addr] = {
                            "username": username_text,
                            "pid": acct_pid,
                        }
                        if acct_pid != TRACKING_PID:
                            with _PLAYER_CONTEXT_LOCK:
                                _PLAYER_CONTEXT_BY_HOST[addr[0]] = {
                                    "username": username_text,
                                    "pid": acct_pid,
                                }
                        # Attach the identity to this auth session immediately;
                        # future secure CONNECTs inherit it by peer above.
                        auth_key = (addr, info["source"])
                        with state_lock:
                            auth_state = connection_state.get(auth_key)
                            if auth_state is not None:
                                auth_state["account_username"] = username_text
                                auth_state["account_pid"] = acct_pid
                        log(f"   *** Login request for user {username!r} "
                            f"-> pid=0x{acct_pid:x} pwd={acct_pwd!r} ***")
                        resp_body = build_login_response(acct_pid, SERVER_PID)
                        label = "LOGIN"
                    elif rmc["method_id"] == 3:        # RequestTicket
                        source_pid, target_pid = struct.unpack_from(
                            "<II", rmc["params"], 0)
                        log(f"   *** RequestTicket source=0x{source_pid:08x} "
                            f"target=0x{target_pid:08x} ***")
                        # This also covers traces where Login was elided from
                        # the capture: the ticket request still identifies the
                        # account principal used by the secure session.
                        account_context_by_peer.setdefault(addr, {})["pid"] = \
                            source_pid
                        ticket_key = (addr, info["source"])
                        with state_lock:
                            ticket_state = connection_state.get(ticket_key)
                            if ticket_state is not None:
                                ticket_state["account_pid"] = source_pid
                        resp_body = build_request_ticket_response(
                            source_pid, target_pid)
                        label = "REQUEST_TICKET"

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_USER_STORAGE \
                        and rmc["method_id"] == 6:
                    # Native progression writer: declare an external body.
                    # The captured DDL request places the byte length and
                    # UserContent type at unaligned offsets 17 and 21.
                    try:
                        body_size = struct.unpack_from("<I", rmc["params"], 17)[0]
                        type_id = struct.unpack_from("<I", rmc["params"], 21)[0]
                    except struct.error:
                        body_size, type_id = 0, 0
                    content_id = 1
                    resp_body = encode_user_content_upload_result(
                        type_id, content_id
                    )
                    label = "USERSTORAGE_CREATE_UPLOAD"
                    log(f"   *** UserStorage create upload "
                        f"type=0x{type_id:08x} size={body_size} "
                        f"content_id={content_id} ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_USER_STORAGE \
                        and rmc["method_id"] == 7:
                    # Finalize the external upload. The response is a
                    # UserContentKey: u32 type ID followed by u64 content ID.
                    try:
                        type_id = struct.unpack_from("<I", rmc["params"], 9)[0]
                        requested_id = struct.unpack_from(
                            "<Q", rmc["params"], 13
                        )[0]
                    except struct.error:
                        type_id, requested_id = 0, 0
                    content_id = requested_id or 1
                    resp_body = struct.pack("<IQ", type_id, content_id)
                    label = "USERSTORAGE_FINALIZE_UPLOAD"
                    log(f"   *** UserStorage finalize upload "
                        f"type=0x{type_id:08x} content_id={content_id} ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_USER_STORAGE \
                        and rmc["method_id"] == 21:
                    # GetOwnContents(type): return the one persisted key for
                    # this local player. A missing file is a valid empty list.
                    try:
                        type_id = struct.unpack_from("<I", rmc["params"], 0)[0]
                    except struct.error:
                        type_id = 0
                    content_id = 1
                    content_path = user_content_path(type_id, content_id)
                    if os.path.isfile(content_path):
                        format_version = user_content_format_version(type_id)
                        resp_body = encode_user_content_rows(
                            type_id, content_id, USER_PID, format_version
                        )
                        row_count = 1
                    else:
                        resp_body = struct.pack("<I", 0)
                        row_count = 0
                    label = "USERSTORAGE_GET_OWN_CONTENTS"
                    log(f"   *** UserStorage own contents "
                        f"type=0x{type_id:08x} rows={row_count}"
                        + (f" format={format_version}"
                           if row_count else "")
                        + " ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_USER_STORAGE \
                        and rmc["method_id"] in (8, 9):
                    # The title may choose an inline DB body (m8) or an
                    # external HTTP GET URL (m9) after GetOwnContents. Support
                    # both with the exact key returned above.
                    try:
                        type_id, content_id = struct.unpack_from(
                            "<IQ", rmc["params"], 0
                        )
                    except struct.error:
                        type_id, content_id = 0, 0
                    content_path = user_content_path(type_id, content_id)
                    if rmc["method_id"] == 8:
                        try:
                            with open(content_path, "rb") as content_file:
                                content_body = content_file.read()
                        except OSError:
                            content_body = b""
                        resp_body = struct.pack("<I", len(content_body)) \
                            + content_body
                        label = "USERSTORAGE_GET_CONTENT_DB"
                        log(f"   *** UserStorage inline content "
                            f"type=0x{type_id:08x} content_id={content_id} "
                            f"size={len(content_body)} ***")
                    else:
                        resp_body = encode_user_content_download_url(
                            type_id, content_id
                        )
                        label = "USERSTORAGE_GET_CONTENT_URL"
                        log(f"   *** UserStorage download URL "
                            f"type=0x{type_id:08x} content_id={content_id} "
                            f"exists={os.path.isfile(content_path)} ***")

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
                        advertised = method_3_response_items(requested, owned)
                        suppressed = [
                            item for item in owned if item not in advertised
                        ]
                        if suppressed:
                            log("   *** Method 3 omitted v1.06 consumable "
                                f"metadata={suppressed}; method 8 replay "
                                "is authoritative ***")
                        owned = advertised
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
                        if INVENTORY_PRICE_PROBE:
                            probed = {
                                item: INVENTORY_PRICE_PROBE[item]
                                for item in owned
                                if item in INVENTORY_PRICE_PROBE
                            }
                            if probed:
                                log("   *** Method 3 price metadata probe="
                                    f"{probed} ***")
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
                            # The refresh remains absent from method-3 inventory;
                            # its method-7 receipt only acknowledges the command.
                            gold, silver = ECONOMY.refresh_store(
                                gold_cost, silver_cost
                            )
                            resp_body = encode_purchase_result(
                                gold, silver, STORE_REFRESH_SENTINEL,
                                transaction_time=encode_qdatetime(),
                                quantity=1,
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
                                gold, silver, item_id,
                                transaction_time=encode_qdatetime(),
                                quantity=1,
                            )
                            label = "MONETIZATION_PURCHASE"
                            log(f"   *** Purchase item={item_id} "
                                f"gold_cost={gold_cost} "
                                f"silver_cost={silver_cost} -> balances "
                                f"gold={gold} silver={silver} ***")
                    elif rmc["method_id"] == 8:     # Enumerate transactions/server time
                        transactions = ECONOMY.method_8_transactions()
                        resp_body = encode_monetization_server_time(
                            transactions=transactions
                        )
                        label = "MONETIZATION_SERVER_TIME"
                        log("   *** Monetization server time; replaying "
                            f"transactions={transactions} ***")
                    elif rmc["method_id"] == 9:     # Consume one item use
                        # Live Face Carver trace: this arrives at fight start
                        # with one item id. Returning gold produced "x99"
                        # because the client stores this u32 as remaining uses
                        # and caps it at 99.
                        try:
                            item_id = struct.unpack_from(
                                "<I", rmc["params"], 0
                            )[0]
                        except struct.error:
                            item_id = 0
                        quantity = ECONOMY.consume_item(item_id)
                        resp_body = struct.pack("<I", quantity)
                        label = "MONETIZATION_CONSUME_ITEM"
                        log(f"   *** Consume item={item_id} "
                            f"remaining={quantity} ***")
                    elif rmc["method_id"] == 10:    # Get consumable remaining count
                        # Static call chain: the v1.00 request stub at
                        # 0x00016844 sends method 10 with one item id. The
                        # "Restoring boost" path at 0x001DC994 stores its one
                        # u32 response as the item's remaining count (capped at
                        # 99 by 0x001DE174). This is not a gold-balance method.
                        try:
                            item_id = struct.unpack_from(
                                "<I", rmc["params"], 0
                            )[0]
                        except struct.error:
                            item_id = 0
                        quantity = ECONOMY.item_quantity(item_id)
                        resp_body = struct.pack("<I", quantity)
                        label = "MONETIZATION_ITEM_QUANTITY"
                        log(f"   *** Item quantity item={item_id} "
                            f"remaining={quantity} ***")
                    elif rmc["method_id"] == 11:    # Finalize gladiator outcome
                        # Live death trace: this follows m12 (death notice) and
                        # m6 (fight income), carrying <Iii> = (gladiator id,
                        # gold cost, silver cost).  The client decodes exactly
                        # two u32 values from its response, just like m6.  A
                        # dead gladiator must not be added to item inventory;
                        # the client has already updated its local roster/status
                        # and this is its completion/settlement boundary.
                        try:
                            gladiator_id, gold_cost, silver_cost = \
                                struct.unpack_from("<Iii", rmc["params"], 0)
                        except struct.error:
                            gladiator_id, gold_cost, silver_cost = 0, -1, -1
                        gold_delta = -gold_cost if gold_cost >= 0 else 0
                        silver_delta = -silver_cost if silver_cost >= 0 else 0
                        gold, silver = ECONOMY.add_income(
                            gold_delta, silver_delta
                        )
                        resp_body = struct.pack("<II", gold, silver)
                        label = "MONETIZATION_GLADIATOR_OUTCOME"
                        log(f"   *** Gladiator outcome id={gladiator_id} "
                            f"gold_cost={gold_cost} silver_cost={silver_cost} "
                            f"-> balances gold={gold} silver={silver} ***")
                    elif rmc["method_id"] == 12:    # Record gladiator death
                        try:
                            gladiator_id = struct.unpack_from(
                                "<I", rmc["params"], 0
                            )[0]
                        except struct.error:
                            gladiator_id = 0
                        # The client applies the dead/status fields locally
                        # before this call and blocks the fight-result flow on
                        # its RMC completion. There are no output parameters.
                        resp_body = b""
                        label = "MONETIZATION_GLADIATOR_DEATH"
                        log(f"   *** Gladiator death id={gladiator_id} ***")
                    elif rmc["method_id"] == 13:    # Recruit gladiator
                        # Live-traced (2026-08-11): the Recruit-store purchase
                        # sends 102/m13 and blocks until answered - the infinite
                        # spinner. Params mirror method 7 (purchase) but for a
                        # gladiator; live captures confirm that the last two
                        # fields are gold/silver costs and use -1 for the unused
                        # currency:
                        # 01.00: id, zero, gold cost, silver cost.
                        # 01.06: id, zero, category, gold cost, silver cost.
                        try:
                            gladiator_id, unk, category, gold_cost, \
                                silver_cost = decode_recruit_request(
                                    rmc["params"]
                                )
                        except struct.error:
                            gladiator_id, unk, category = 0, 0, None
                            gold_cost = silver_cost = -1
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
                                gold, silver, gladiator_id,
                                transaction_time=encode_qdatetime(),
                                quantity=1,
                            )
                        label = "MONETIZATION_RECRUIT"
                        log(f"   *** Recruit gladiator={gladiator_id} unk={unk} "
                            f"category={category} "
                            f"gold_cost={gold_cost} silver_cost={silver_cost} "
                            f"shape={shape} -> balances gold={gold} silver={silver} ***")
                    elif rmc["method_id"] == 15:    # Replace gladiator perk
                        # Live-traced (2026-08-12): the Ludus perk swap sends
                        #   u32 gladiator_id, u32 perk_id, i32 gold_cost
                        # Two swaps of DIFFERENT perks (100061, 100002) on the
                        # same gladiator both carried 2, matching the 2-gold
                        # price the player is shown, and neither client nor
                        # server debited it - the swap was free.  Its parser
                        # case body (0x00018EBC) returns a single u32 that the
                        # client applies as the gold balance, so answer with the
                        # post-debit balance.
                        #   P102M15_DEBIT=0  disables the debit if the third
                        #                    parameter turns out not to be a cost
                        try:
                            gladiator_id, perk_id, gold_cost = \
                                struct.unpack_from("<IIi", rmc["params"], 0)
                        except struct.error:
                            gladiator_id, perk_id, gold_cost = 0, 0, -1
                        debit = (gold_cost if gold_cost >= 0 else 0)
                        if os.environ.get("P102M15_DEBIT", "1") == "0":
                            debit = 0
                        gold, silver = ECONOMY.add_income(-debit, 0)
                        resp_body = struct.pack("<I", gold)
                        label = "MONETIZATION_PERK_SWAP"
                        log(f"   *** Perk swap gladiator={gladiator_id} "
                            f"perk={perk_id} gold_cost={gold_cost} "
                            f"debited={debit} -> gold={gold} ***")
                    elif rmc["method_id"] == 19:    # Get reward balances (01.06)
                        # Methods 19 and 20 share parser case 0x000435A4 in
                        # 01.06. It decodes exactly three u32 output slots.
                        # Returning the old generic receipt made its third
                        # word an item id of zero, overwriting fame at login.
                        with ECONOMY.lock:
                            gold = ECONOMY.data["gold"]
                            silver = ECONOMY.data["silver"]
                            fame = ECONOMY.data["fame"]
                        resp_body = encode_reward_balances(gold, silver, fame)
                        label = "MONETIZATION_REWARD_BALANCES"
                        log(f"   *** Reward balances gold={gold} "
                            f"silver={silver} fame={fame} ***")
                    elif rmc["method_id"] == 20:    # Deposit fight rewards (01.06)
                        # Recovered from the 01.06 client on 2026-08-26:
                        # request stub 0x0003F0E0 serializes three i32 values;
                        # parser vtable entry 23 at 0x000434E4 decodes exactly
                        # three u32 outputs. The fight caller at 0x001D3EF0
                        # supplies gold, silver and fame reward deltas in that
                        # order. The response contains their absolute balances.
                        try:
                            gold_delta, silver_delta, fame_delta = \
                                struct.unpack_from("<iii", rmc["params"], 0)
                        except struct.error:
                            gold_delta = silver_delta = fame_delta = 0
                        gold, silver, fame = ECONOMY.add_rewards(
                            gold_delta, silver_delta, fame_delta
                        )
                        resp_body = encode_reward_balances(gold, silver, fame)
                        label = "MONETIZATION_FIGHT_REWARDS"
                        log(f"   *** Fight rewards gold={gold_delta:+d} "
                            f"silver={silver_delta:+d} fame={fame_delta:+d} "
                            f"-> balances gold={gold} silver={silver} "
                            f"fame={fame} ***")
                    elif rmc["method_id"] == 24:    # Enumerate Shop records (01.06)
                        # Parser case 0x00043918 calls the structured-list
                        # decoder at 0x0054F638.  The post-load roster validator
                        # removes every native owned record whose +0x08 key is
                        # absent from this result, so mirror the keys from the
                        # authoritative type-3 save instead of returning an
                        # empty list.
                        content_id = int(os.environ.get(
                            "SPARTACUS_USER_CONTENT_ID", "1"
                        ), 0)
                        shop_records = read_v106_owned_gladiator_records(content_id)
                        resp_body = encode_shop_records(shop_records)
                        label = "MONETIZATION_SHOP_RECORDS"
                        log("   *** Shop records -> owned gladiators "
                            f"{list(shop_records)} ***")
                    else:
                        # UNHANDLED shop method.  Protocol 102 is the one
                        # protocol excluded from the GENERIC_ACK fallback below,
                        # so before this branch an unrecognised method received a
                        # bare transport ACK and no RMC reply at all: the client
                        # blocks forever on its async job (the infinite shop
                        # spinner, escapable only by killing RPCS3).  Always
                        # answer with a well-formed response so an unimplemented
                        # shop feature degrades to "that action failed" instead
                        # of hanging, and log enough to implement it properly.
                        #
                        # Default shape is the proven m7/m13 receipt because it
                        # is a superset of the m6/m11 balance pair: a client
                        # expecting only <gold, silver> reads those two fields
                        # and ignores the trailing receipt.  Nothing is debited -
                        # which params are costs is unknown for an unidentified
                        # method, and a wrong debit corrupts the profile.
                        # Iterate without editing code:
                        #   P102M17_SHAPE=balances   (this method only)
                        #   P102_FALLBACK_SHAPE=...  (every unknown method)
                        # shapes: receipt | balances | empty | zero | result |
                        #         error[:code]
                        method = rmc["method_id"]
                        # Precedence: per-method override, then global override,
                        # then the shape recovered from the client's parser,
                        # then the receipt (superset of the balance pair).
                        shape = os.environ.get(
                            f"P102M{method}_SHAPE",
                            os.environ.get(
                                "P102_FALLBACK_SHAPE",
                                P102_METHOD_SHAPES.get(method, "receipt"),
                            ),
                        )
                        raw = rmc["params"]
                        words = list(struct.unpack_from(
                            f"<{len(raw) // 4}I", raw, 0
                        )) if len(raw) >= 4 else []
                        # Costs are i32 and use -1 as the "not this currency"
                        # sentinel, so show a signed view too - that is what
                        # identified the gold/silver fields of m11 and m13.
                        signed = [w - 0x100000000 if w > 0x7FFFFFFF else w
                                  for w in words]
                        with ECONOMY.lock:
                            gold = ECONOMY.data["gold"]
                            silver = ECONOMY.data["silver"]
                        if shape == "balances":
                            resp_body = struct.pack("<II", gold, silver)
                        elif shape == "gold":
                            resp_body = struct.pack("<I", gold)
                        elif shape == "silver":
                            resp_body = struct.pack("<I", silver)
                        elif shape == "empty":
                            resp_body = b""
                        elif shape == "zero":
                            resp_body = struct.pack("<I", 0)
                        elif shape == "result":
                            resp_body = struct.pack("<I", 0x00010001)
                        elif shape.startswith("error"):
                            _, _, code = shape.partition(":")
                            resp_error = int(code, 0) if code else 0x80010001
                            resp_body = b""
                        else:  # "receipt"
                            # Echo the first parameter as the transaction id;
                            # m7 and m13 both carry the item/gladiator id first.
                            resp_body = encode_purchase_result(
                                gold, silver, words[0] if words else 0,
                                transaction_time=encode_qdatetime(),
                                quantity=1,
                            )
                        label = f"MONETIZATION_UNHANDLED(m{method})"
                        log(f"   *** UNHANDLED Monetization method={method} "
                            f"call={rmc['call_id']} params={raw.hex()} "
                            f"({len(raw)}B) u32={words} i32={signed} ***")
                        log(f"   *** replying [{shape}] to avoid a client hang; "
                            f"no currency debited (balances gold={gold} "
                            f"silver={silver}). Please report this method. ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_TOURNAMENT \
                        and rmc["method_id"] == 7 \
                        and (PROTO_TOURNAMENT, 7) not in PROTO_OVERRIDES:
                    resp_body = encode_no_joined_tournament_season()
                    label = "TOURNAMENT_GET_JOINED_SEASON_NONE"
                    log("   *** Tournament method 7 GetJoinedSeason -> "
                        f"not joined ({len(resp_body)}B structured result) ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_PATCH_VERSION \
                        and (PROTO_PATCH_VERSION,
                             rmc["method_id"]) not in PROTO_OVERRIDES:
                    # An explicit P106M<n>=<shape> override still wins, so a
                    # live test can force a different shape entirely without
                    # editing this branch.
                    method = rmc["method_id"]
                    if method == 1:
                        resp_body, fields = encode_patch_version_response()
                        label = "PATCHVERSION_GET_CURRENT"
                        log(f"   *** PatchVersion method 1 -> "
                            f"{fields} ({len(resp_body)}B); compared fields "
                            f"are {fields[:3]} ***")
                    else:
                        # The client only implements methods 1 and 2, and
                        # treats 2 as a no-op. Anything else raises 0x80010002
                        # client-side, so an empty body is the safe answer.
                        resp_body = b""
                        label = f"PATCHVERSION_EMPTY(m{method})"
                        log(f"   *** PatchVersion method={method} answered "
                            f"empty (client implements only 1 and 2) ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_CHALLENGE \
                        and rmc["method_id"] in (1, 2, 3, 4) \
                        and (PROTO_CHALLENGE, rmc["method_id"]) \
                        not in PROTO_OVERRIDES:
                    method = rmc["method_id"]
                    if method in (1, 3):
                        try:
                            challenge_id = struct.unpack_from(
                                "<I", rmc["params"],
                                4 if method == 1 else 0
                            )[0]
                        except struct.error:
                            challenge_id = 0
                        reward = V106_CHALLENGE_REWARDS.get(challenge_id)
                        daily = method == 3
                        correct_claim_path = (
                            challenge_id in V106_DAILY_CHALLENGE_IDS
                        ) == daily
                        credited = bool(reward) and correct_claim_path and \
                            ECONOMY.claim_challenge_reward(
                                reward, daily=daily
                            )
                        response_reward = (
                            reward if credited else (0, 0, 0, 0, 0, 0)
                        )
                        resp_body = encode_v106_challenge_reward(
                            response_reward
                        )
                        response_fields = struct.unpack("<6I", resp_body)
                        label = (
                            "CHALLENGE_CLAIM_DAILY_REWARD" if daily else
                            "CHALLENGE_CLAIM_REWARD"
                        )
                        log(f"   *** Challenge claim={challenge_id} "
                            f"daily={daily} reward={reward or 'unknown'} "
                            f"credited={credited} "
                            f"-> rpc_fields={response_fields} ***")
                    else:
                        daily = method == 4
                        completed = ECONOMY.completed_challenges(daily=daily)
                        resp_body = struct.pack(
                            f"<I{len(completed)}I", len(completed), *completed
                        )
                        label = (
                            "CHALLENGE_GET_COMPLETED_DAILY" if daily else
                            "CHALLENGE_GET_COMPLETED"
                        )
                        log(f"   *** Challenge method {method} -> completed "
                            f"{completed} ***")

                elif rmc and rmc["is_request"] \
                        and rmc["protocol"] == PROTO_LOGIN_REWARD \
                        and rmc["method_id"] in (1, 2, 3, 4) \
                        and DAILY_LOGIN_REWARDS_ENABLED \
                        and (PROTO_LOGIN_REWARD, rmc["method_id"]) \
                        not in PROTO_OVERRIDES:
                    method = rmc["method_id"]
                    if method == 1:
                        # Static request stub 0x00034868 serializes u32 + bool;
                        # the response parser reads exactly one bool.
                        try:
                            player_pid = struct.unpack_from(
                                "<I", rmc["params"], 0
                            )[0]
                            client_flag = struct.unpack_from(
                                "<?", rmc["params"], 4
                            )[0]
                        except struct.error:
                            player_pid, client_flag = 0, False
                        granted = ECONOMY.register_daily_login()
                        resp_body = struct.pack("<?", granted)
                        label = "LOGINREWARD_DAILY_LOGIN"
                        log(f"   *** DailyLogin pid=0x{player_pid:08x} "
                            f"client_flag={client_flag} granted={granted} "
                            f"stash={ECONOMY.daily_login_rewards()} ***")
                    elif method in (2, 3):
                        rewards, current_stage, reset_seconds = \
                            ECONOMY.daily_login_info()
                        resp_body = encode_v106_daily_login_reward_list(
                            rewards
                        )
                        resp_body += struct.pack(
                            "<II", current_stage, reset_seconds
                        )
                        if method == 3:
                            resp_body += struct.pack("<Q", encode_qdatetime())
                        label = f"LOGINREWARD_GET_INFO(m{method})"
                        log(f"   *** LoginReward info method={method} "
                            f"rewards={rewards} "
                            f"current_stage={current_stage} "
                            f"reset_seconds={reset_seconds} ***")
                    else:
                        # Static request stub 0x00032E48 serializes one u32;
                        # the response is a list of the shared reward DTO.
                        try:
                            player_pid = struct.unpack_from(
                                "<I", rmc["params"], 0
                            )[0]
                        except struct.error:
                            player_pid = 0
                        rewards = ECONOMY.claim_daily_login_rewards()
                        resp_body = encode_v106_daily_login_reward_list(
                            rewards
                        )
                        label = "LOGINREWARD_CLAIM"
                        log(f"   *** ClaimLoginRewards "
                            f"pid=0x{player_pid:08x} rewards={rewards} "
                            f"balances=({ECONOMY.data['gold']}, "
                            f"{ECONOMY.data['silver']}, "
                            f"{ECONOMY.data['fame']}) ***")

                elif rmc and rmc["is_request"] \
                        and (rmc["protocol"], rmc["method_id"]) \
                        not in PROTO_OVERRIDES \
                        and (static_body := encode_v106_protocol_response(
                            rmc["protocol"], rmc["method_id"], rmc["params"]
                        )) is not None:
                    resp_body = static_body
                    label = (f"V106_STATIC(p{rmc['protocol']}"
                             f"m{rmc['method_id']})")
                    if (rmc["protocol"] == PROTO_CHALLENGE \
                            and rmc["method_id"] == 1):
                        challenge_id = (
                            struct.unpack_from("<I", rmc["params"], 4)[0]
                            if len(rmc["params"]) >= 8 else 0
                        )
                        reward = V106_CHALLENGE_REWARDS.get(challenge_id)
                        log(f"   *** Challenge method 1 claim={challenge_id} "
                            f"-> retail reward row {reward or 'unknown/zero'} "
                            f"({len(resp_body)}B; economy not credited yet) ***")
                    else:
                        log(f"   *** {PROTO_NAMES.get(rmc['protocol'], 'v1.06')} "
                            f"method {rmc['method_id']} -> statically proven "
                            f"inactive result ({len(resp_body)}B) ***")

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
                        # qlist<UserContent>. The Crixus selection loop looks
                        # up ContentProperty ID 5, requires variant type 5
                        # (u64), and rejects a zero value before dispatching
                        # the external-content request. After download it also
                        # requires property ID 101 as an uppercase SHA-256
                        # string, then copies integer property ID 100.
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
                        sha256_hex = os.environ.get(
                            "SPARTACUS_REMOTE_CONFIG_SHA256",
                            "7913A13830F32D6E2F8314A4A343422C"
                            "BBC4F0F98ABEB10373C908E9AC7F8E30",
                        )
                        resp_body = encode_remote_config_content(
                            type_id, content_id, owner_pid, sha256_hex
                        )
                        shape = ("user_content_stub["
                                 f"type=0x{type_id:08x}, "
                                 f"content={content_id}, "
                                 f"pid=0x{owner_pid:08x}, "
                                 "properties=[5:u64(1), 100:i64(1), "
                                 f"101:string({sha256_hex})]]")
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
                    elif shape == "external_content_url":
                        protocol = os.environ.get(
                            "P53M9_PROTOCOL", "http://")
                        host = os.environ.get("P53M9_HOST", "127.0.0.1")
                        path = os.environ.get(
                            "P53M9_PATH", "/remoteconfig.bin")
                        resp_body = encode_user_content_url(
                            protocol, host, path)
                        shape = (f"external_content_url[protocol={protocol!r}, "
                                 f"host={host!r}, path={path!r}]")
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
                    rmc_msg = (
                        build_rmc_error(rmc["protocol"], rmc["call_id"],
                                        resp_error)
                        if resp_error is not None else
                        build_rmc_response(rmc["protocol"], rmc["call_id"],
                                           rmc["method_id"], resp_body)
                    )
                    packets = build_data_fragments(
                        src, dst, sess, seq + 1,
                        client_conn_sig.get(addr, 0), rmc_msg,
                    )
                    for pkt in packets:
                        srv.sendto(pkt, addr)
                    conn_key = (addr, info["source"])
                    remember_server_sequence(
                        conn_key, seq + 1 + len(packets)
                    )
                    packet_sizes = ",".join(str(len(pkt)) for pkt in packets)
                    log(f"-> {label} RESPONSE ({len(packets)} fragment(s): "
                        f"{packet_sizes}B, rmc={len(rmc_msg)}B)")

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
                    if not any(key[0] == addr for key in connection_state):
                        account_context_by_peer.pop(addr, None)
            else:
                log(f"   (no handler for {tname})")
    except KeyboardInterrupt:
        if owns_stop_event:
            log("Shutting down.")
    finally:
        srv.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else PORT)
