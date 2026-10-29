#!/usr/bin/env python3
"""Offline save editor core for the Spartacus Legends preservation data.

Qt-free: the PySide6 frontend calls these functions and the unit tests exercise
them directly with temporary directories.  Nothing here starts a server,
connects to RPCS3, or touches a live game session.

Authority (see notes/22-qt-frontend-and-adaptive-patch-plan.md):

- ``data/usercontent[<version>]/80000001/1.bin`` is the native profile the
  client restores.  Its balances are big-endian u32 words at
  ``title_save_migration.PROFILE_BALANCE_OFFSETS``.  The 01.00 file is exactly
  4664 bytes (``0x1238``); any other size is an unknown layout and is refused.
- ``profile.json`` (``prudp_server.EconomyStore``) is the server's companion
  copy of balances plus ``owned_items`` / ``item_quantities``.

A save is one operation: back up both files with a SHA-256 manifest, write the
three balance words into the native profile, then rewrite the companion JSON
keeping every other key.  The editor refuses to write while a caller reports
that the server is running: ``EconomyStore`` keeps the companion in memory and
would overwrite external edits, and a running game would autosave over the
native object.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
import uuid

try:
    import migration_coordinator
    import prudp_server
    import title_save_migration
except ImportError:  # Imported as tools.save_editor by the unit tests.
    from tools import migration_coordinator
    from tools import prudp_server
    # title_save_migration imports migration_coordinator by its bare module
    # name. Publish the package-qualified object under that name so the
    # ``tools.`` import style works without tools/ being on sys.path.
    sys.modules.setdefault("migration_coordinator", migration_coordinator)
    from tools import title_save_migration


# The documented 01.00 profile object size.  The client accepts this layout for
# 01.06 too (see title_save_migration); the balance offsets are only corroborated
# for this layout, so an editor write requires it exactly.
NATIVE_PROFILE_SIZE = 0x1238

MAX_QUANTITY = 99
U32_MAX = 0xFFFFFFFF

# Above this value the game's on-screen formatting is unverified.  This is a
# hypothesis flag only: the value is still written unless it exceeds u32.
DISPLAY_WARNING_THRESHOLD = 9_999_999

BACKUP_DIR_NAME = "backups"
BACKUP_PREFIX = "editor-"
MANIFEST_NAME = "manifest.json"
BACKUP_FORMAT = "spartacus-save-editor-backup"
BACKUP_FORMAT_VERSION = 1

BALANCE_NAMES = tuple(title_save_migration.PROFILE_BALANCE_OFFSETS)

# Item groups are labels only, keyed by the client's ``item_id / 10000`` family
# rule (notes/16-v106-daily-login-boost-handoff.md).  No item names are invented.
GROUP_FAMILIES = {
    1: "1xxxx",
    2: "2xxxx",
    3: "3xxxx",
    4: "4xxxx",
}
GROUP_BOOSTS = "Boosts (60000-60063)"
GROUP_SLOTS = "Ludus slots (80002-80007)"
GROUP_OTHER = "Other IDs"
GROUP_ORDER = (
    "1xxxx",
    "2xxxx",
    "3xxxx",
    "4xxxx",
    GROUP_BOOSTS,
    GROUP_SLOTS,
    GROUP_OTHER,
)


def native_profile_holds_balances(title_version) -> bool:
    """Whether the native type-1 object is where this build keeps balances.

    01.00 restores gold/silver/fame from ``+0x04/+0x0C/+0x14`` of its 4664-byte
    profile.  01.06 does not: every 0x15B8 profile the 01.06 client wrote in the
    live tests under ``.build`` holds zero in those words and nowhere else
    contains the companion's values, while Shop method 19 (login) and method 20
    (after each fight) hand the client all three absolute balances from the
    server's economy store.  For 01.06 the companion JSON is the only authority
    and the native object is never touched.
    """
    version = migration_coordinator.coerce_title_version(title_version)
    return version is migration_coordinator.TitleVersion.V100


class SaveEditorError(RuntimeError):
    """A refused or failed save-editor operation; nothing is left half-written."""


# The Quazal auth/secure ports every server launch reserves (UDP). Port 80 is
# not probed: IIS and other web servers hold it without being this server.
SERVER_PROBE_HOST = "127.0.0.1"
SERVER_PROBE_PORTS = (21000, 21001)


def external_server_reason(host: str = SERVER_PROBE_HOST,
                           ports=SERVER_PROBE_PORTS) -> str | None:
    """Return why a server appears to be running outside the GUI, or None.

    The GUI only knows about a server it started itself. A console server (or
    a second GUI) holds the same economy in memory and would overwrite an
    offline edit, so probe the ports it reserves. Binding uses the same
    exclusive mode as ``reserve_ports``; the probe socket is closed at once.
    """
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET,
                                socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((host, port))
        except OSError as error:
            return (f"UDP port {port} on {host} is already in use ({error}). "
                    "A Spartacus Legends server appears to be running outside "
                    "this window (for example SpartacusLegendsServer.exe in a "
                    "console). Stop it first: its in-memory economy would "
                    "overwrite these edits. If another program holds the port, "
                    "close that program instead.")
        finally:
            sock.close()
    return None


def _refuse_if_external_server(action: str) -> None:
    reason = external_server_reason()
    if reason is not None:
        raise SaveEditorError(f"refusing to {action}: {reason}")


@dataclass(frozen=True)
class TitlePaths:
    """Resolved save locations for one selected title build."""

    data_dir: Path
    title_version: migration_coordinator.TitleVersion
    user_content_dir: Path
    companion_path: Path
    native_profile_path: Path


@dataclass(frozen=True)
class EditorState:
    """Read-only snapshot of the native profile and economy companion."""

    paths: TitlePaths
    native_present: bool
    native_size: int | None
    native_balances: dict[str, int] | None
    companion_balances: dict[str, int]
    owned_items: tuple[int, ...]
    item_quantities: dict[int, int]
    mismatch_fields: tuple[str, ...]
    # False for builds (01.06) whose balances live only on the server.
    native_holds_balances: bool = True

    @property
    def mismatch(self) -> bool:
        """True when the native and companion balances disagree."""
        return bool(self.mismatch_fields)

    @property
    def effective_balances(self) -> dict[str, int]:
        """Native values when the profile exists, else the companion copy."""
        if self.native_balances is not None:
            return dict(self.native_balances)
        return dict(self.companion_balances)


@dataclass(frozen=True)
class SaveResult:
    """Outcome of one atomic save, including the backup that was created."""

    paths: TitlePaths
    backup_dir: Path
    manifest_path: Path
    backed_up_files: tuple[str, ...]
    balances: dict[str, int]
    owned_items: tuple[int, ...]
    item_quantities: dict[int, int]
    native_written: bool
    companion_written: bool
    warnings: tuple[str, ...]

    @property
    def companion_only(self) -> bool:
        return not self.native_written


@dataclass(frozen=True)
class BackupInfo:
    """One restorable ``data/backups/editor-*`` directory."""

    name: str
    path: Path
    created_at: str
    title_version: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class RestoreResult:
    backup_dir: Path
    title_version: str
    restored_files: tuple[str, ...]


# --------------------------------------------------------------- path rules

def title_paths(data_dir: Path,
                title_version=migration_coordinator.DEFAULT_TITLE_VERSION
                ) -> TitlePaths:
    """Resolve the native and companion paths for one build.

    This mirrors ``spartacus_server.configure_environment``: 01.00 keeps the
    shipped ``data/profile.json`` + ``data/usercontent/`` layout; any other
    build uses a version-namespaced user-content directory and its own
    companion file (``data/profile-<version>.json``).  The user-content rule is
    taken straight from ``migration_coordinator.native_content_dir`` so there is
    only one definition of it.
    """
    data_dir = Path(data_dir)
    version = migration_coordinator.coerce_title_version(title_version)
    user_content_dir = migration_coordinator.native_content_dir(
        data_dir, version)
    if version is migration_coordinator.TitleVersion.V100:
        companion_path = data_dir / migration_coordinator.LEGACY_PROFILE_FILE
    else:
        companion_path = data_dir / f"profile-{version.value}.json"
    native_profile_path = (
        user_content_dir
        / f"{title_save_migration.PROFILE_TYPE:08x}"
        / f"{migration_coordinator.NATIVE_CONTENT_ID}.bin"
    )
    return TitlePaths(
        data_dir=data_dir,
        title_version=version,
        user_content_dir=user_content_dir,
        companion_path=companion_path,
        native_profile_path=native_profile_path,
    )


# ------------------------------------------------------------ companion view

def _read_companion_document(path: Path) -> dict:
    """Return the companion JSON object, or ``{}`` when the file is absent.

    A present-but-unreadable companion is an error, not "empty": silently
    treating it as empty would replace the player's economy with defaults.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise SaveEditorError(f"could not read {path}: {error}") from error
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SaveEditorError(
            f"the economy companion {path} is not valid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise SaveEditorError(
            f"the economy companion {path} must contain a JSON object")
    return document


def _economy_store(path: Path) -> "prudp_server.EconomyStore":
    """Load the companion through the server's own normalisation rules."""
    return prudp_server.EconomyStore(str(path))


def _read_native_profile(path: Path) -> bytes:
    """Read the native profile, refusing any layout other than 4664 bytes."""
    try:
        payload = Path(path).read_bytes()
    except FileNotFoundError:
        raise
    except OSError as error:
        raise SaveEditorError(f"could not read {path}: {error}") from error
    if len(payload) != NATIVE_PROFILE_SIZE:
        raise SaveEditorError(
            f"the native profile {path} is {len(payload)} bytes, but the "
            f"documented 01.00 layout is exactly {NATIVE_PROFILE_SIZE} bytes. "
            "Refusing to edit an unrecognised layout; restore a backup or "
            "let the game write a fresh profile."
        )
    return payload


def _native_balances(payload: bytes) -> dict[str, int]:
    return {
        name: struct.unpack_from(">I", payload, offset)[0]
        for name, offset in title_save_migration.PROFILE_BALANCE_OFFSETS.items()
    }


def load(data_dir: Path,
         title_version=migration_coordinator.DEFAULT_TITLE_VERSION
         ) -> EditorState:
    """Read the native profile and the economy companion.

    A missing ``1.bin`` is normal for a fresh player: the native balances are
    ``None`` and the companion values are used.  A present-but-wrong-sized
    ``1.bin`` is a recovery condition and is refused rather than treated as
    absent, matching the server's native-object rules.
    """
    paths = title_paths(data_dir, title_version)
    holds_balances = native_profile_holds_balances(paths.title_version)
    native_balances = None
    native_size = None
    native_present = paths.native_profile_path.is_file()
    if native_present and holds_balances:
        payload = _read_native_profile(paths.native_profile_path)
        native_size = len(payload)
        native_balances = _native_balances(payload)
    elif native_present:
        # Shown for information only; its layout is never parsed or edited.
        native_size = paths.native_profile_path.stat().st_size

    _read_companion_document(paths.companion_path)
    store = _economy_store(paths.companion_path)
    companion_balances = {
        name: int(store.data[name]) for name in BALANCE_NAMES
    }
    owned_items = tuple(int(item) for item in store.data["owned_items"])
    item_quantities = {
        int(item): int(quantity)
        for item, quantity in store.data["item_quantities"].items()
    }
    mismatch_fields = ()
    if native_balances is not None:
        mismatch_fields = tuple(
            name for name in BALANCE_NAMES
            if native_balances[name] != companion_balances[name]
        )
    return EditorState(
        paths=paths,
        native_present=native_present,
        native_size=native_size,
        native_balances=native_balances,
        companion_balances=companion_balances,
        owned_items=owned_items,
        item_quantities=item_quantities,
        mismatch_fields=mismatch_fields,
        native_holds_balances=holds_balances,
    )


# ---------------------------------------------------------- item normalisation

def _parse_item_id(value) -> int:
    """Validate one user-supplied item ID (add-by-ID entry)."""
    if isinstance(value, bool):
        raise SaveEditorError("an item ID must be a whole number")
    try:
        item_id = int(value)
    except (TypeError, ValueError) as error:
        raise SaveEditorError(
            f"an item ID must be a whole number, not {value!r}") from error
    if not 0 <= item_id <= U32_MAX:
        raise SaveEditorError(f"item ID {item_id} does not fit in 32 bits")
    if item_id == prudp_server.STORE_REFRESH_SENTINEL:
        raise SaveEditorError(
            f"{prudp_server.STORE_REFRESH_SENTINEL} is the recruitment-store "
            "refresh command, not an item")
    return item_id


def normalise_owned_items(items) -> tuple[int, ...]:
    """Mirror ``EconomyStore._load``: u32-mask, drop sentinel, sort.

    The refresh command ID is dropped rather than raised on here because this
    normalises data that is already on disk; interactive add-by-ID uses
    :func:`add_owned_item`, which refuses it outright.
    """
    values = set()
    for item in items:
        try:
            item_id = int(item) & U32_MAX
        except (TypeError, ValueError) as error:
            raise SaveEditorError(
                f"owned item ID {item!r} is not a whole number") from error
        if item_id == prudp_server.STORE_REFRESH_SENTINEL:
            continue
        values.add(item_id)
    return tuple(sorted(values))


def normalise_item_quantities(quantities, owned_items
                              ) -> dict[int, int]:
    """Mirror ``EconomyStore._load`` for ``item_quantities``.

    Counts are clamped to 0..99, malformed rows are skipped, and only owned
    items keep a count (the store drops counts for anything else).
    """
    owned = set(normalise_owned_items(owned_items))
    result: dict[int, int] = {}
    for item, quantity in dict(quantities or {}).items():
        try:
            item_id = int(item) & U32_MAX
            count = max(0, min(MAX_QUANTITY, int(quantity)))
        except (TypeError, ValueError):
            continue
        if item_id in owned:
            result[item_id] = count
    return result


def add_owned_item(owned_items, item_id) -> tuple[int, ...]:
    """Return the item list with one ID added (interactive add-by-ID)."""
    item_id = _parse_item_id(item_id)
    return tuple(sorted(set(normalise_owned_items(owned_items)) | {item_id}))


def remove_owned_item(owned_items, item_id) -> tuple[int, ...]:
    """Return the item list without one ID.

    Removing a Ludus slot entitlement is allowed offline (the plan's warning is
    a UI concern); the live control channel is what refuses it.
    """
    item_id = _parse_item_id(item_id)
    items = normalise_owned_items(owned_items)
    if item_id not in set(items):
        raise SaveEditorError(f"item {item_id} is not owned")
    return tuple(item for item in items if item != item_id)


def set_item_quantity(item_quantities, owned_items, item_id,
                      quantity) -> dict[int, int]:
    """Return the quantity map with one owned item's count set (0..99)."""
    item_id = _parse_item_id(item_id)
    if isinstance(quantity, bool):
        raise SaveEditorError("an item quantity must be a whole number")
    try:
        count = int(quantity)
    except (TypeError, ValueError) as error:
        raise SaveEditorError(
            f"an item quantity must be a whole number, not {quantity!r}"
        ) from error
    owned = set(normalise_owned_items(owned_items))
    if item_id not in owned:
        raise SaveEditorError(f"item {item_id} is not owned; add it first")
    if not 0 <= count <= MAX_QUANTITY:
        raise SaveEditorError(
            f"item quantity must be between 0 and {MAX_QUANTITY}")
    result = normalise_item_quantities(item_quantities, owned)
    result[item_id] = count
    return result


def effective_quantity(owned_items, item_quantities, item_id) -> int:
    """Count shown for one item, mirroring ``EconomyStore.item_quantity``."""
    item_id = int(item_id)
    if item_id not in set(normalise_owned_items(owned_items)):
        return 0
    quantities = {
        int(item): int(quantity)
        for item, quantity in dict(item_quantities or {}).items()
    }
    return quantities.get(
        item_id, prudp_server.LEGACY_CONSUMABLE_USES.get(item_id, 1))


# ------------------------------------------------------------- item grouping

def is_ludus_slot(item_id) -> bool:
    value = int(item_id)
    return (prudp_server.SLOT_ENTITLEMENT_MIN
            <= value <= prudp_server.SLOT_ENTITLEMENT_MAX)


def is_boost(item_id) -> bool:
    value = int(item_id)
    return (prudp_server.CONSUMABLE_ITEM_ID_MIN
            <= value <= prudp_server.CONSUMABLE_ITEM_ID_MAX)


def quantity_editable(item_id) -> bool:
    """Only the Boost ID range has an editable use count."""
    return is_boost(item_id)


def item_group(item_id) -> str:
    """Group label for one ID, using observed ID ranges only."""
    value = int(item_id)
    if is_boost(value):
        return GROUP_BOOSTS
    if is_ludus_slot(value):
        return GROUP_SLOTS
    family = value // 10000
    if family in GROUP_FAMILIES:
        return GROUP_FAMILIES[family]
    return GROUP_OTHER


def group_items(items) -> dict[str, tuple[int, ...]]:
    """Group owned item IDs into the fixed, ordered display groups."""
    grouped: dict[str, list[int]] = {name: [] for name in GROUP_ORDER}
    for item in items:
        value = int(item)
        grouped[item_group(value)].append(value)
    return {
        name: tuple(sorted(values))
        for name, values in grouped.items()
        if values
    }


# ------------------------------------------------------------------- backup

def _atomic_write(path: Path, payload: bytes) -> None:
    """Write ``payload`` beside ``path`` then replace it atomically."""
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


def _relative_to_data_dir(data_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(data_dir.resolve()))
    except ValueError as error:
        raise SaveEditorError(
            f"refusing to back up a file outside the data directory: {path}"
        ) from error


def _create_backup(data_dir: Path,
                   title_version: migration_coordinator.TitleVersion,
                   entries: list[tuple[Path, bytes]]
                   ) -> tuple[Path, Path, tuple[str, ...]]:
    """Copy the given files into a fresh ``data/backups/editor-*`` folder.

    ``entries`` are ``(absolute path, bytes at the time of backup)`` pairs; the
    companion bytes are the pre-edit content.  Returns the folder, manifest
    path, and the relative file names recorded in the manifest.
    """
    timestamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = data_dir / BACKUP_DIR_NAME
    backup_dir = backup_root / f"{BACKUP_PREFIX}{timestamp}"
    counter = 0
    while backup_dir.exists():
        counter += 1
        backup_dir = backup_root / f"{BACKUP_PREFIX}{timestamp}-{counter}"

    manifest_files: dict[str, dict] = {}
    backed_up_files: list[str] = []
    try:
        for source, payload in entries:
            relative = _relative_to_data_dir(data_dir, source)
            _atomic_write(backup_dir / relative, payload)
            manifest_files[relative] = {
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            backed_up_files.append(relative)
        manifest = {
            "format": BACKUP_FORMAT,
            "version": BACKUP_FORMAT_VERSION,
            "created_at": _datetime.datetime.now().isoformat(
                timespec="seconds"),
            "title_version": title_version.value,
            "data_dir": str(data_dir.resolve()),
            "files": manifest_files,
        }
        manifest_path = backup_dir / MANIFEST_NAME
        _atomic_write(
            manifest_path,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"),
        )
    except OSError as error:
        raise SaveEditorError(
            f"could not create the pre-edit backup {backup_dir}: {error}"
        ) from error
    return backup_dir, manifest_path, tuple(backed_up_files)


def _read_manifest(path: Path) -> dict | None:
    """Return a validated backup manifest, or None when it is not one."""
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if document.get("format") != BACKUP_FORMAT:
        return None
    if not isinstance(document.get("files"), dict):
        return None
    return document


def list_backups(data_dir: Path) -> list[BackupInfo]:
    """List the restorable save-editor backups, newest first."""
    backup_root = Path(data_dir) / BACKUP_DIR_NAME
    if not backup_root.is_dir():
        return []
    backups: list[BackupInfo] = []
    for candidate in backup_root.iterdir():
        if not candidate.is_dir():
            continue
        if not candidate.name.startswith(BACKUP_PREFIX):
            continue
        manifest = _read_manifest(candidate / MANIFEST_NAME)
        if manifest is None:
            continue
        backups.append(BackupInfo(
            name=candidate.name,
            path=candidate,
            created_at=str(manifest.get("created_at", "")),
            title_version=str(manifest.get("title_version", "")),
            files=tuple(sorted(manifest["files"])),
        ))
    backups.sort(key=lambda backup: backup.name, reverse=True)
    return backups


# --------------------------------------------------------------------- save

def _clamp_balance(name: str, value, source: str) -> tuple[int, list[str]]:
    if isinstance(value, bool):
        raise SaveEditorError(f"{name} must be a whole number")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise SaveEditorError(
            f"{name} must be a whole number, not {value!r}") from error
    warnings: list[str] = []
    if number < 0:
        warnings.append(f"{name} {number} ({source}) is negative; clamped to 0.")
        number = 0
    if number > U32_MAX:
        warnings.append(
            f"{name} {number} ({source}) does not fit in 32 bits; clamped to "
            f"{U32_MAX}.")
        number = U32_MAX
    elif number > DISPLAY_WARNING_THRESHOLD:
        warnings.append(
            f"{name} {number} is above {DISPLAY_WARNING_THRESHOLD:,}. The "
            "game's on-screen display limit is unknown (hypothesis: large "
            "values may display incorrectly). The value was written unchanged."
        )
    return number, warnings


def save(data_dir: Path,
         title_version=migration_coordinator.DEFAULT_TITLE_VERSION,
         *,
         gold=None,
         silver=None,
         fame=None,
         owned_items=None,
         item_quantities=None,
         server_running: bool = False) -> SaveResult:
    """Back up, then atomically write balances (and optional inventory).

    ``gold`` / ``silver`` / ``fame`` of ``None`` keep the companion's current
    value.  ``owned_items`` / ``item_quantities`` of ``None`` leave the
    companion inventory untouched; supplying them replaces it after applying
    the ``EconomyStore`` normalisation rules.  Every unrecognised companion key
    and every native byte outside the three balance words is preserved.

    Refuses up front when ``server_running`` is true: the in-memory economy
    store would overwrite external edits, and a running game would autosave
    over the native object.
    """
    if server_running:
        raise SaveEditorError(
            "refusing to edit save files while the server is running. Stop the "
            "server, return to the Ludus, wait about 20 seconds, and close "
            "RPCS3 first. Live edits use the server's control channel instead."
        )
    _refuse_if_external_server("edit save files")

    paths = title_paths(data_dir, title_version)
    data_dir = paths.data_dir

    # Validate everything before the backup or any write.
    holds_balances = native_profile_holds_balances(paths.title_version)
    native_payload = None
    if holds_balances and paths.native_profile_path.is_file():
        native_payload = _read_native_profile(paths.native_profile_path)

    companion_document = _read_companion_document(paths.companion_path)
    companion_payload = (
        paths.companion_path.read_bytes()
        if paths.companion_path.is_file() else None
    )
    store = _economy_store(paths.companion_path)

    requested = {"gold": gold, "silver": silver, "fame": fame}
    balances: dict[str, int] = {}
    warnings: list[str] = []
    for name in BALANCE_NAMES:
        if requested[name] is None:
            value, source = int(store.data[name]), "existing companion value"
        else:
            value, source = requested[name], "edited"
        balances[name], clamp_warnings = _clamp_balance(name, value, source)
        warnings.extend(clamp_warnings)

    if owned_items is None:
        final_owned_items = tuple(
            int(item) for item in store.data["owned_items"])
    else:
        final_owned_items = normalise_owned_items(owned_items)
    stored_quantities = {
        int(item): int(quantity)
        for item, quantity in store.data["item_quantities"].items()
    }
    if item_quantities is None:
        final_item_quantities = normalise_item_quantities(
            stored_quantities, final_owned_items)
    else:
        final_item_quantities = normalise_item_quantities(
            item_quantities, final_owned_items)

    updated = dict(companion_document)
    updated.update(balances)
    if owned_items is not None:
        updated["owned_items"] = list(final_owned_items)
    if item_quantities is not None or owned_items is not None:
        updated["item_quantities"] = {
            str(item): quantity
            for item, quantity in sorted(final_item_quantities.items())
        }
    companion_bytes = (
        json.dumps(updated, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    entries: list[tuple[Path, bytes]] = []
    if native_payload is not None:
        entries.append((paths.native_profile_path, native_payload))
    if companion_payload is not None:
        entries.append((paths.companion_path, companion_payload))
    backup_dir, manifest_path, backed_up_files = _create_backup(
        data_dir, paths.title_version, entries)

    native_written = False
    if native_payload is not None:
        edited_native = bytearray(native_payload)
        for name, offset in \
                title_save_migration.PROFILE_BALANCE_OFFSETS.items():
            struct.pack_into(">I", edited_native, offset, balances[name])
        try:
            _atomic_write(paths.native_profile_path, bytes(edited_native))
        except OSError as error:
            raise SaveEditorError(
                f"writing the native profile failed after the backup at "
                f"{backup_dir}: {error}") from error
        native_written = True
    elif holds_balances:
        warnings.append(
            "The native profile (1.bin) does not exist yet, so only the "
            "companion profile was edited. The game's next native autosave "
            "will create it."
        )

    try:
        _atomic_write(paths.companion_path, companion_bytes)
    except OSError as error:
        raise SaveEditorError(
            f"writing the companion profile failed after the backup at "
            f"{backup_dir}: {error}") from error

    return SaveResult(
        paths=paths,
        backup_dir=backup_dir,
        manifest_path=manifest_path,
        backed_up_files=backed_up_files,
        balances=dict(balances),
        owned_items=tuple(final_owned_items),
        item_quantities=dict(sorted(final_item_quantities.items())),
        native_written=native_written,
        companion_written=True,
        warnings=tuple(warnings),
    )


# ------------------------------------------------------------------ restore

def restore_backup(data_dir: Path, backup_name: str, *,
                   server_running: bool = False) -> RestoreResult:
    """Restore one backup after verifying every file against its manifest.

    All hashes are checked before anything is written, so a tampered or
    incomplete backup leaves the current save untouched.  Files are written
    atomically.
    """
    if server_running:
        raise SaveEditorError(
            "refusing to restore a backup while the server is running. Stop "
            "the server and close RPCS3 first."
        )
    _refuse_if_external_server("restore a backup")
    name = str(backup_name)
    if not name or Path(name).name != name or name in (".", ".."):
        raise SaveEditorError(f"invalid backup name {backup_name!r}")
    backup_root = Path(data_dir) / BACKUP_DIR_NAME
    backup_dir = backup_root / name
    manifest = _read_manifest(backup_dir / MANIFEST_NAME)
    if manifest is None:
        raise SaveEditorError(
            f"{backup_dir} is not a save-editor backup (missing or invalid "
            f"{MANIFEST_NAME})")

    data_root = Path(data_dir).resolve()
    verified: list[tuple[Path, bytes]] = []
    for relative_name in sorted(manifest["files"]):
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SaveEditorError(
                f"backup manifest {backup_dir} contains an unsafe path: "
                f"{relative_name}")
        source = backup_dir / relative
        if not source.is_file():
            raise SaveEditorError(
                f"backup {name} is incomplete: {relative_name} is missing")
        try:
            payload = source.read_bytes()
        except OSError as error:
            raise SaveEditorError(
                f"could not read backup file {source}: {error}") from error
        entry = manifest["files"][relative_name]
        expected_hash = str(entry.get("sha256", "")) if isinstance(
            entry, dict) else ""
        actual_hash = hashlib.sha256(payload).hexdigest()
        if not expected_hash or actual_hash != expected_hash:
            raise SaveEditorError(
                f"backup file {relative_name} fails SHA-256 verification "
                f"(manifest: {expected_hash or 'missing'}, found: "
                f"{actual_hash}). Refusing to restore.")
        destination = data_root / relative
        try:
            destination.resolve().relative_to(data_root)
        except ValueError as error:
            raise SaveEditorError(
                f"backup manifest {backup_dir} escapes the data directory: "
                f"{relative_name}") from error
        verified.append((destination, payload))

    for destination, payload in verified:
        try:
            _atomic_write(destination, payload)
        except OSError as error:
            raise SaveEditorError(
                f"restoring {destination} failed: {error}") from error
    return RestoreResult(
        backup_dir=backup_dir,
        title_version=str(manifest.get("title_version", "")),
        restored_files=tuple(
            _relative_to_data_dir(Path(data_dir), destination)
            for destination, _payload in verified
        ),
    )
