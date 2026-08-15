#!/usr/bin/env python3
"""Remove owned Legends so they can be recruited again.

Recovery finds Legend instances directly from any supported roster snapshot,
removes them from the bridge snapshot and wherever they occur in the game's
compact native roster, and preserves campaign state so the defeated Legends
remain eligible for recruitment.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import sys
import tempfile


TITLE_SAVE_DIR = "NPUB30746-STYAUTO-"
PRG_NAME = "PRG-DATA"
SECTION_MAGIC = b"SECTION\0"
SECTION_DATA_OFFSET = 0x14
SECTION_ONE_SIZE = 0xCA88

# Section one is copied from its resident object at object+8.  The native roster
# serializer receives object+0xB848, so its structure begins at section+0xB840.
NATIVE_ROSTER_OFFSET = 0xB840
NATIVE_ROSTER_VERSION_OFFSET = 0x18
NATIVE_ROSTER_COUNT_OFFSET = 0x1C
NATIVE_ROSTER_ENTRIES_OFFSET = 0x2A
NATIVE_ROSTER_ENTRY_SIZE = 0x10
NATIVE_ROSTER_VERSION = 7
MAX_NATIVE_ROSTER = 40

KNOWN_LEGENDS = {
    9: "Oenomaus",
    10: "Acolytus",
    12: "Ixion",
    14: "Masonius",
}


class RecoveryError(RuntimeError):
    """Raised when recovery cannot prove that an edit is safe."""


@dataclass(frozen=True)
class RosterLegend:
    slot: int
    product_id: int
    token: str

    @property
    def display_name(self) -> str:
        return KNOWN_LEGENDS.get(self.product_id, self.token)


@dataclass(frozen=True)
class NativeRoster:
    section_start: int
    structure_start: int
    count: int
    entries: tuple[bytes, ...]

    @property
    def product_ids(self) -> tuple[int, ...]:
        return tuple(struct.unpack_from(">H", entry)[0] for entry in self.entries)


@dataclass(frozen=True)
class RecoveryPlan:
    data_dir: Path
    save_dir: Path
    prg_path: Path
    roster: dict
    legends: tuple[RosterLegend, ...]
    native: NativeRoster

    @property
    def product_ids(self) -> tuple[int, ...]:
        return tuple(legend.product_id for legend in self.legends)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"could not read {path}: {error}") from error
    if not isinstance(value, dict):
        raise RecoveryError(f"{path} does not contain a JSON object")
    return value


def _decode_backing(words: object, slot: int) -> str:
    if not isinstance(words, list) or not words:
        raise RecoveryError(f"roster backing {slot} is malformed")
    try:
        raw = b"".join(bytes.fromhex(word) for word in words)
    except (TypeError, ValueError) as error:
        raise RecoveryError(f"roster backing {slot} contains invalid hex") from error
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")


def find_roster_legends(roster: dict) -> tuple[RosterLegend, ...]:
    schema = roster.get("schema_version")
    if schema not in (1, 2, 3):
        raise RecoveryError(f"unsupported roster schema {schema!r}")

    records = roster.get("records")
    backings = roster.get("backings")
    count = roster.get("count")
    if (not isinstance(records, list) or not isinstance(backings, list) or
            not isinstance(count, int) or count != len(records) or
            count != len(backings)):
        raise RecoveryError("roster count, records, and backings do not agree")

    legends = []
    for slot, (record, backing) in enumerate(zip(records, backings)):
        token = _decode_backing(backing, slot)
        if "_LEGEND_" not in token:
            continue
        if not isinstance(record, list) or len(record) < 2:
            raise RecoveryError(f"Legend record {slot} is malformed")
        try:
            word = record[1]
            if not isinstance(word, str) or len(word) != 16:
                raise ValueError
            product_id = int(word[:8], 16)
        except (TypeError, ValueError) as error:
            raise RecoveryError(
                f"could not decode the product ID in Legend record {slot}"
            ) from error
        if not 0 < product_id <= 0xFFFF:
            raise RecoveryError(
                f"Legend record {slot} has implausible product ID {product_id}"
            )
        legends.append(RosterLegend(slot, product_id, token))

    if not legends:
        raise RecoveryError("roster contains no Legend records")
    if schema == 3:
        blocks = roster.get("blocks")
        if not isinstance(blocks, list) or len(blocks) != count:
            raise RecoveryError("schema-3 roster count and blocks do not agree")
    return tuple(legends)


# Retain the old internal name for callers of the initial recovery module.
find_broken_legends = find_roster_legends


def locate_save_dir(rpcs3_root: Path) -> Path:
    root = rpcs3_root.expanduser().resolve()
    savedata = root / "dev_hdd0" / "home"
    matches = sorted(savedata.glob(f"*/savedata/{TITLE_SAVE_DIR}"))
    matches = [path for path in matches if (path / PRG_NAME).is_file()]
    if not matches:
        raise RecoveryError(f"could not find {TITLE_SAVE_DIR} under {root}")
    if len(matches) != 1:
        choices = "\n  ".join(str(path) for path in matches)
        raise RecoveryError(
            "multiple Spartacus Legends saves were found; pass --save-dir instead:\n"
            f"  {choices}"
        )
    return matches[0]


def parse_native_roster(prg: bytes) -> NativeRoster:
    sections = []
    cursor = 0
    while True:
        cursor = prg.find(SECTION_MAGIC, cursor)
        if cursor < 0:
            break
        if cursor + 12 <= len(prg):
            section_id = struct.unpack_from(">I", prg, cursor + 8)[0]
            if section_id == 1:
                sections.append(cursor)
        cursor += len(SECTION_MAGIC)
    if len(sections) != 1:
        raise RecoveryError(
            f"expected one section-1 record in PRG-DATA, found {len(sections)}"
        )

    section_start = sections[0]
    data_start = section_start + SECTION_DATA_OFFSET
    if data_start + SECTION_ONE_SIZE > len(prg):
        raise RecoveryError("PRG-DATA section 1 is truncated")
    structure_start = data_start + NATIVE_ROSTER_OFFSET
    version = struct.unpack_from(
        ">I", prg, structure_start + NATIVE_ROSTER_VERSION_OFFSET
    )[0]
    if version != NATIVE_ROSTER_VERSION:
        raise RecoveryError(
            f"unsupported native roster version {version}; expected "
            f"{NATIVE_ROSTER_VERSION}"
        )
    count = struct.unpack_from(
        ">H", prg, structure_start + NATIVE_ROSTER_COUNT_OFFSET
    )[0]
    if count > MAX_NATIVE_ROSTER:
        raise RecoveryError(f"implausible native roster count {count}")
    entries_start = structure_start + NATIVE_ROSTER_ENTRIES_OFFSET
    entries_end = entries_start + count * NATIVE_ROSTER_ENTRY_SIZE
    if entries_end > data_start + SECTION_ONE_SIZE:
        raise RecoveryError("native roster entries escape section 1")
    entries = tuple(
        prg[offset:offset + NATIVE_ROSTER_ENTRY_SIZE]
        for offset in range(entries_start, entries_end, NATIVE_ROSTER_ENTRY_SIZE)
    )
    return NativeRoster(section_start, structure_start, count, entries)


def build_plan(data_dir: Path, save_dir: Path) -> RecoveryPlan:
    data_dir = data_dir.expanduser().resolve()
    save_dir = save_dir.expanduser().resolve()
    roster_path = data_dir / "roster.json"
    campaign_path = data_dir / "campaign.json"
    prg_path = save_dir / PRG_NAME
    if not campaign_path.is_file():
        raise RecoveryError(f"missing {campaign_path}")
    if not prg_path.is_file():
        raise RecoveryError(f"missing {prg_path}")

    roster = _read_json(roster_path)
    legends = find_roster_legends(roster)
    try:
        prg = prg_path.read_bytes()
    except OSError as error:
        raise RecoveryError(f"could not read {prg_path}: {error}") from error
    native = parse_native_roster(prg)

    return RecoveryPlan(data_dir, save_dir, prg_path, roster, legends, native)


def _recovered_roster(plan: RecoveryPlan) -> dict:
    removed_slots = {legend.slot for legend in plan.legends}
    result = dict(plan.roster)
    result["records"] = [
        record for slot, record in enumerate(plan.roster["records"])
        if slot not in removed_slots
    ]
    result["backings"] = [
        backing for slot, backing in enumerate(plan.roster["backings"])
        if slot not in removed_slots
    ]
    if plan.roster.get("schema_version") == 3:
        result["blocks"] = [
            block for slot, block in enumerate(plan.roster["blocks"])
            if slot not in removed_slots
        ]
    result["count"] = len(result["records"])
    result["captured_at"] = _datetime.datetime.now().astimezone().isoformat()
    return result


def _recovered_prg(plan: RecoveryPlan, original: bytes) -> bytes:
    target_ids = set(plan.product_ids)
    kept = [
        entry for entry in plan.native.entries
        if struct.unpack_from(">H", entry)[0] not in target_ids
    ]
    result = bytearray(original)
    count_offset = plan.native.structure_start + NATIVE_ROSTER_COUNT_OFFSET
    entries_start = plan.native.structure_start + NATIVE_ROSTER_ENTRIES_OFFSET
    old_entries_end = entries_start + plan.native.count * NATIVE_ROSTER_ENTRY_SIZE
    struct.pack_into(">H", result, count_offset, len(kept))
    packed = b"".join(kept)
    result[entries_start:old_entries_end] = packed + bytes(
        old_entries_end - entries_start - len(packed)
    )
    if len(result) != len(original):
        raise RecoveryError("internal error: PRG-DATA size changed")
    return bytes(result)


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _pine_is_reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def apply_plan(plan: RecoveryPlan, backup_root: Path | None = None,
               pine_port: int = 28012) -> Path:
    if _pine_is_reachable(pine_port):
        raise RecoveryError(
            f"RPCS3 PINE is reachable on port {pine_port}; close RPCS3 and the "
            "preservation server before applying recovery"
        )

    roster_path = plan.data_dir / "roster.json"
    campaign_path = plan.data_dir / "campaign.json"
    original_roster = roster_path.read_bytes()
    original_campaign = campaign_path.read_bytes()
    original_prg = plan.prg_path.read_bytes()

    # Revalidate immediately before writing so a running bridge or game cannot
    # silently replace one of the files between dry-run and apply.
    current = build_plan(plan.data_dir, plan.save_dir)
    if current.product_ids != plan.product_ids or current.native != plan.native:
        raise RecoveryError("save data changed after the recovery plan was built")

    recovered_document = _recovered_roster(plan)
    recovered_roster = None if recovered_document["count"] == 0 else (
        json.dumps(recovered_document, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    recovered_prg = _recovered_prg(plan, original_prg)
    parsed_after = parse_native_roster(recovered_prg)
    if any(product in parsed_after.product_ids for product in plan.product_ids):
        raise RecoveryError("post-edit validation still found a removed product")

    timestamp = _datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    if backup_root is None:
        backup_root = plan.data_dir.parent / "recovery-backups"
    backup_dir = backup_root.expanduser().resolve() / f"legend-recovery-{timestamp}"
    if backup_dir.exists():
        raise RecoveryError(f"backup destination already exists: {backup_dir}")
    server_backup = backup_dir / "server-data"
    native_backup = backup_dir / "native-save"
    server_backup.mkdir(parents=True)
    for name in ("roster.json", "campaign.json", "profile.json"):
        source = plan.data_dir / name
        if source.is_file():
            shutil.copy2(source, server_backup / name)
    shutil.copytree(plan.save_dir, native_backup)

    manifest = {
        "created_at": _datetime.datetime.now().astimezone().isoformat(),
        "removed": [
            {
                "slot": legend.slot,
                "product_id": legend.product_id,
                "name": legend.display_name,
                "token": legend.token,
            }
            for legend in plan.legends
        ],
        "original": {
            "roster_sha256": _sha256(original_roster),
            "campaign_sha256": _sha256(original_campaign),
            "prg_data_sha256": _sha256(original_prg),
        },
        "recovered": {
            "roster_sha256": (_sha256(recovered_roster)
                               if recovered_roster is not None else None),
            "roster_action": ("updated" if recovered_roster is not None
                              else "removed_empty_snapshot"),
            "campaign_sha256": _sha256(original_campaign),
            "prg_data_sha256": _sha256(recovered_prg),
        },
    }
    (backup_dir / "recovery.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    try:
        if recovered_roster is None:
            roster_path.unlink()
        else:
            _atomic_write(roster_path, recovered_roster)
        _atomic_write(plan.prg_path, recovered_prg)
        if campaign_path.read_bytes() != original_campaign:
            raise RecoveryError("campaign.json changed during recovery")
    except Exception:
        # The complete originals are already durable in backup_dir.  Restore the
        # two files this utility writes so a partial operation is never exposed.
        _atomic_write(roster_path, original_roster)
        _atomic_write(plan.prg_path, original_prg)
        raise
    return backup_dir


def describe_plan(plan: RecoveryPlan) -> str:
    lines = [
        f"Server data: {plan.data_dir}",
        f"Native save: {plan.prg_path}",
        f"Roster: {plan.roster['count']} bridge entries, "
        f"{plan.native.count} native entries",
        "Broken Legends to make recruitable again:",
    ]
    for legend in plan.legends:
        native_count = plan.native.product_ids.count(legend.product_id)
        native_note = (f", {native_count} native entr"
                       f"{'y' if native_count == 1 else 'ies'}")
        lines.append(
            f"  slot {legend.slot + 1}: {legend.display_name} "
            f"(product {legend.product_id}{native_note})"
        )
    lines.extend((
        f"Result: {plan.roster['count'] - len(plan.legends)} roster entries",
        "campaign.json: preserved unchanged",
    ))
    return "\n".join(lines)


def run_recovery(data_dir: Path, rpcs3_root: Path | None = None,
                 save_dir: Path | None = None, apply: bool = False,
                 backup_root: Path | None = None, pine_port: int = 28012) -> int:
    if (rpcs3_root is None) == (save_dir is None):
        raise RecoveryError("provide exactly one of RPCS3 root or save directory")
    resolved_save = (locate_save_dir(rpcs3_root) if rpcs3_root is not None
                     else save_dir.expanduser().resolve())
    plan = build_plan(data_dir, resolved_save)
    print(describe_plan(plan))
    if not apply:
        print("\nDRY RUN: no files changed. Re-run with --apply to perform recovery.")
        return 0
    backup_dir = apply_plan(plan, backup_root, pine_port)
    print(f"\nRecovery applied. Complete backup: {backup_dir}")
    print("Cold-boot the game, open Recruit, and refresh until each Legend appears.")
    return 0


def _parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rpcs3_root", nargs="?", type=Path)
    parser.add_argument("--save-dir", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--pine-port", type=int, default=28012)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return run_recovery(
            args.data_dir, args.rpcs3_root, args.save_dir, args.apply,
            args.backup_root, args.pine_port,
        )
    except RecoveryError as error:
        print(f"RECOVERY ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
