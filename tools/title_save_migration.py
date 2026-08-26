"""Explicit 01.00 -> 01.06 native-save migration.

This is deliberately separate from normal server startup.  The profile is
copied byte-for-byte because the 01.06 client accepts its 01.00 layout.  The
campaign and roster bodies are preserved and extended by the areas added in
01.06.  Live evidence shows new Nemesis state in the appended campaign area
and proved that an unextended old roster falls back despite the old size being
recognized by another apply mode.  The zero-initialized extensions passed the
documented client rewrite and cold-boot restoration test on a progressed save.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import uuid

import migration_coordinator as mc


PROFILE_TYPE = 0x80000001
CAMPAIGN_TYPE = 0x80000002
ROSTER_TYPE = 0x80000003
TYPE_IDS = (PROFILE_TYPE, CAMPAIGN_TYPE, ROSTER_TYPE)
MARKER_NAME = "migration-01.00-to-01.06.json"

# The 01.00 profile begins with three big-endian balance fields separated by
# unused u32 words.  Gold and silver are independently corroborated by the
# economy companion.  Fame was not stored in old profile.json releases, so it
# is carried forward from the third native field.
PROFILE_BALANCE_OFFSETS = {"gold": 0x04, "silver": 0x0C, "fame": 0x14}


class TitleSaveMigrationError(RuntimeError):
    """The migration preflight failed without changing the active data."""


@dataclass(frozen=True)
class MigrationResult:
    backup_path: Path
    destination_root: Path
    companion_path: Path
    marker_path: Path
    balances: dict[str, int]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_exact(path: Path, expected_size: int) -> bytes:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as error:
        raise TitleSaveMigrationError(f"required 01.00 save is missing: {path}") \
            from error
    except OSError as error:
        raise TitleSaveMigrationError(f"could not read {path}: {error}") \
            from error
    if len(payload) != expected_size:
        raise TitleSaveMigrationError(
            f"wrong-sized 01.00 save {path}: expected {expected_size} bytes, "
            f"found {len(payload)}"
        )
    return payload


def _load_economy_companion(path: Path, profile: bytes) -> tuple[dict, dict]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TitleSaveMigrationError(
            f"required 01.00 economy companion is missing: {path}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TitleSaveMigrationError(
            f"could not read 01.00 economy companion {path}: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise TitleSaveMigrationError(
            f"01.00 economy companion must contain a JSON object: {path}"
        )
    if not isinstance(loaded.get("owned_items"), list):
        raise TitleSaveMigrationError(
            f"01.00 economy companion has no valid owned_items list: {path}"
        )

    balances = {
        name: struct.unpack_from(">I", profile, offset)[0]
        for name, offset in PROFILE_BALANCE_OFFSETS.items()
    }
    for name in ("gold", "silver"):
        try:
            companion_value = int(loaded[name])
        except (KeyError, TypeError, ValueError) as error:
            raise TitleSaveMigrationError(
                f"01.00 economy companion has no valid {name} value: {path}"
            ) from error
        if companion_value != balances[name]:
            raise TitleSaveMigrationError(
                f"01.00 {name} mismatch: native profile has "
                f"{balances[name]}, economy companion has {companion_value}. "
                "Resolve the inconsistent save before migrating."
            )
    if "fame" in loaded:
        try:
            companion_fame = int(loaded["fame"])
        except (TypeError, ValueError) as error:
            raise TitleSaveMigrationError(
                f"01.00 economy companion has an invalid fame value: {path}"
            ) from error
        if companion_fame != balances["fame"]:
            raise TitleSaveMigrationError(
                f"01.00 fame mismatch: native profile has {balances['fame']}, "
                f"economy companion has {companion_fame}. Resolve the "
                "inconsistent save before migrating."
            )

    migrated = dict(loaded)
    migrated.update(balances)
    migrated.setdefault("claimed_challenges", [])
    migrated.setdefault("daily_challenges", {"date": "", "claimed": []})
    return migrated, balances


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _create_backup(data_dir: Path) -> Path:
    timestamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    root = data_dir.parent / mc.BACKUP_DIR_NAME
    backup = root / f"data-before-01.06-migration-{timestamp}"
    counter = 0
    while backup.exists():
        counter += 1
        backup = root / f"data-before-01.06-migration-{timestamp}-{counter}"
    try:
        shutil.copytree(data_dir, backup)
    except OSError as error:
        raise TitleSaveMigrationError(
            f"could not create pre-migration backup {backup}: {error}"
        ) from error
    return backup


def _remove_existing(path: Path) -> None:
    """Remove one already-backed-up migration destination."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def migrate_v100_to_v106(data_dir: Path,
                          replace_existing: bool = False) -> MigrationResult:
    """Create an isolated 01.06 namespace from complete 01.00 native saves.

    All validation happens before the backup or destination is created.
    Existing 01.06 data is never overwritten.
    """
    data_dir = Path(data_dir).resolve()
    if not data_dir.is_dir():
        raise TitleSaveMigrationError(f"data directory does not exist: {data_dir}")

    source_root = mc.native_content_dir(data_dir, mc.TitleVersion.V100)
    destination_root = mc.native_content_dir(data_dir, mc.TitleVersion.V106)
    destination_companion = data_dir / "profile-01.06.json"
    marker_path = data_dir / MARKER_NAME
    conflicts = [
        path for path in (destination_root, destination_companion, marker_path)
        if path.exists()
    ]
    if conflicts and not replace_existing:
        joined = ", ".join(str(path) for path in conflicts)
        raise TitleSaveMigrationError(
            "01.06 destination already exists; refusing to overwrite: " + joined
        )

    v100_table = mc.native_objects(mc.TitleVersion.V100)
    source_paths = {
        type_id: source_root / f"{type_id:08x}" / f"{mc.NATIVE_CONTENT_ID}.bin"
        for type_id in TYPE_IDS
    }
    source = {
        type_id: _read_exact(source_paths[type_id],
                             v100_table[type_id].expected_size)
        for type_id in TYPE_IDS
    }
    companion, balances = _load_economy_companion(
        data_dir / mc.LEGACY_PROFILE_FILE, source[PROFILE_TYPE]
    )

    v106_table = mc.native_objects(mc.TitleVersion.V106)
    campaign_extension_size = (
        v106_table[CAMPAIGN_TYPE].expected_size
        - len(source[CAMPAIGN_TYPE])
    )
    if campaign_extension_size != 0x400:
        raise TitleSaveMigrationError(
            "internal campaign-size assumption changed; refusing migration"
        )
    roster_extension_size = (
        v106_table[ROSTER_TYPE].expected_size - len(source[ROSTER_TYPE])
    )
    if roster_extension_size != 4:
        raise TitleSaveMigrationError(
            "internal roster-size assumption changed; refusing migration"
        )
    output = {
        PROFILE_TYPE: source[PROFILE_TYPE],
        CAMPAIGN_TYPE: source[CAMPAIGN_TYPE] + bytes(campaign_extension_size),
        ROSTER_TYPE: source[ROSTER_TYPE] + bytes(roster_extension_size),
    }
    companion_bytes = (
        json.dumps(companion, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    backup = _create_backup(data_dir)
    try:
        if replace_existing:
            for path in conflicts:
                _remove_existing(path)
        for type_id in TYPE_IDS:
            target = (destination_root / f"{type_id:08x}" /
                      f"{mc.NATIVE_CONTENT_ID}.bin")
            _atomic_write(target, output[type_id])
        _atomic_write(destination_companion, companion_bytes)

        marker = {
            "status": "created_pending_client_rewrite",
            "source_version": "01.00",
            "destination_version": "01.06",
            "backup_path": str(backup),
            "replaced_existing_01.06": bool(conflicts),
            "campaign_conversion": {
                "method": "preserve_01.00_body_and_append_zero_extension",
                "source_size": len(source[CAMPAIGN_TYPE]),
                "extension_size": campaign_extension_size,
                "destination_size": len(output[CAMPAIGN_TYPE]),
            },
            "roster_conversion": {
                "method": "preserve_01.00_body_and_append_zero_trailer_word",
                "source_size": len(source[ROSTER_TYPE]),
                "extension_size": roster_extension_size,
                "destination_size": len(output[ROSTER_TYPE]),
            },
            "balances": balances,
            "objects": {
                f"0x{type_id:08X}": {
                    "source_path": str(source_paths[type_id]),
                    "source_size": len(source[type_id]),
                    "source_sha256": _sha256(source[type_id]),
                    "destination_size": len(output[type_id]),
                    "destination_sha256": _sha256(output[type_id]),
                }
                for type_id in TYPE_IDS
            },
            "created_at": _datetime.datetime.now().isoformat(timespec="seconds"),
        }
        _atomic_write(
            marker_path,
            (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
    except OSError as error:
        raise TitleSaveMigrationError(
            f"migration write failed after backup {backup}: {error}"
        ) from error

    return MigrationResult(
        backup_path=backup,
        destination_root=destination_root,
        companion_path=destination_companion,
        marker_path=marker_path,
        balances=balances,
    )
