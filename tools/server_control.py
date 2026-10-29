#!/usr/bin/env python3
"""JSON command channel for the running server (opt-in ``--control-stdin``).

The Qt frontend never edits ``profile.json`` while the server owns it. Instead
it writes one JSON object per line to the server's stdin; the server applies
the change under ``EconomyStore``'s existing lock, saves atomically, and writes
one prefixed reply line to stdout. The plain line ``stop`` asks for the normal
clean shutdown; end-of-file on stdin never stops the server.

This module is Qt-free and does not import :mod:`prudp_server`: the caller
passes the live ``EconomyStore`` instance.
"""

from __future__ import annotations

import json

REPLY_PREFIX = "@@REPLY "

SUPPORTED_COMMANDS = (
    "get_economy",
    "set_balances",
    "set_fame",
    "add_item",
    "remove_item",
    "set_item_quantity",
)


_FAME_REFUSAL = (
    "Fame cannot be changed while the server is running on 01.00: that "
    "client has no live fame update. Stop the server and edit fame offline "
    "in the Player tab."
)


def _error(message: str) -> dict:
    return {"ok": False, "error": str(message)}


def _economy_state(store) -> dict:
    with store.lock:
        return {
            "gold": store.data["gold"],
            "silver": store.data["silver"],
            "fame": store.data["fame"],
            "owned_items": list(store.data["owned_items"]),
            "item_quantities": {
                str(item): quantity
                for item, quantity in store.data["item_quantities"].items()
            },
        }


def _whole_number(request: dict, key: str) -> int:
    value = request[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a whole number")
    return value


# Builds whose client receives absolute fame from the server mid-session:
# 01.06 Shop method 19 (login) and method 20 (after each fight) both decode
# gold, silver and fame. No 01.00 response is known to carry fame.
LIVE_FAME_TITLE_VERSIONS = frozenset({"01.06"})


def live_fame_supported(title_version) -> bool:
    return str(title_version) in LIVE_FAME_TITLE_VERSIONS


def handle_command(store, request: dict, title_version: str = "01.00") -> dict:
    """Apply one command object and return the reply object (without ``id``).

    Every failure is a JSON reply, never an exception: the channel is the GUI's
    only live control path and must not take the server down.
    """
    command = request.get("cmd")
    try:
        if command == "get_economy":
            return {"ok": True, **_economy_state(store)}
        if command == "set_balances":
            if "gold" not in request and "silver" not in request:
                return _error("set_balances needs gold and/or silver")
            gold = _whole_number(request, "gold") if "gold" in request else None
            silver = (
                _whole_number(request, "silver")
                if "silver" in request else None
            )
            fame = None
            if "fame" in request:
                if not live_fame_supported(title_version):
                    return _error(_FAME_REFUSAL)
                fame = _whole_number(request, "fame")
            if fame is None:
                gold, silver = store.set_balances(gold=gold, silver=silver)
                return {"ok": True, "gold": gold, "silver": silver}
            gold, silver, fame = store.set_balances(
                gold=gold, silver=silver, fame=fame)
            return {"ok": True, "gold": gold, "silver": silver, "fame": fame}
        if command == "add_item":
            if "item_id" not in request:
                return _error("add_item needs item_id")
            item_id = _whole_number(request, "item_id")
            quantity = (
                _whole_number(request, "quantity")
                if "quantity" in request else 1
            )
            item_id, quantity = store.add_owned_item(item_id, quantity)
            return {"ok": True, "item_id": item_id, "quantity": quantity}
        if command == "remove_item":
            if "item_id" not in request:
                return _error("remove_item needs item_id")
            item_id = store.remove_owned_item(
                _whole_number(request, "item_id"))
            return {"ok": True, "item_id": item_id}
        if command == "set_item_quantity":
            if "item_id" not in request or "quantity" not in request:
                return _error("set_item_quantity needs item_id and quantity")
            item_id = _whole_number(request, "item_id")
            quantity = store.set_item_quantity(
                item_id, _whole_number(request, "quantity"))
            return {"ok": True, "item_id": item_id, "quantity": quantity}
        if command == "set_fame":
            # On 01.00 this is a deliberate refusal: no live-traced response
            # pushes fame to that client, so a live edit would silently fail
            # (or be overwritten by the next native autosave).
            if not live_fame_supported(title_version):
                return _error(_FAME_REFUSAL)
            if "fame" not in request:
                return _error("set_fame needs fame")
            _gold, _silver, fame = store.set_balances(
                fame=_whole_number(request, "fame"))
            return {"ok": True, "fame": fame}
        if command is None:
            return _error(
                "missing cmd; supported: " + ", ".join(SUPPORTED_COMMANDS)
            )
        return _error(
            f"unknown command {command!r}; supported: "
            + ", ".join(SUPPORTED_COMMANDS)
        )
    except (TypeError, ValueError, KeyError, OSError) as error:
        return _error(error)


def handle_line(store, text: str, title_version: str = "01.00") -> dict:
    """Parse one stdin line and return the reply dict (with echoed ``id``)."""
    try:
        request = json.loads(text)
    except json.JSONDecodeError as error:
        return _error(f"invalid JSON: {error.msg}")
    if not isinstance(request, dict):
        return _error("each command must be one JSON object")
    reply = handle_command(store, request, title_version)
    if "id" in request:
        reply = {"id": request["id"], **reply}
    return reply


def serve_control_channel(stop_event, store, lines, write_reply,
                          title_version: str = "01.00") -> None:
    """Read commands until EOF; ``stop`` sets ``stop_event`` and continues.

    EOF is deliberately not a stop: a GUI that closes its pipe must not take
    the server down. The caller runs this in a daemon thread.
    """
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        if text == "stop":
            stop_event.set()
            continue
        write_reply(
            REPLY_PREFIX
            + json.dumps(handle_line(store, text, title_version),
                         separators=(",", ":"), sort_keys=True)
        )
