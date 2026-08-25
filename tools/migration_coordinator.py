"""v0.3 -> v0.4 native save migration coordinator (Phase 1).

Pure detection/validation/state logic per notes/07-v0.4-save-migration-plan.md.
This module never opens a PINE connection, never starts a thread, and never
mutates anything except through the explicit backup and marker calls.

Authority rules implemented here:

- A structurally valid native object is authoritative.
- Legacy JSON may restore an object only when the native object is absent.
- A malformed or wrong-sized native object blocks migration; it is never
  treated as absent.
- Detection and state are independent per object type.
- No legacy file is deleted or modified.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


MIGRATION_MARKER_NAME = "migration-v0.4.json"
BACKUP_DIR_NAME = "backups"

# Content id 1 is the only slot the game uploads for each type.
NATIVE_CONTENT_ID = 1

# Legacy JSON file name and the key that must exist (besides
# schema_version) for the file to count as a structurally valid migration
# source.
LEGACY_FILES = {
    0x80000002: ("campaign.json", "cells"),
    0x80000003: ("roster.json", "records"),
}

# Type 1 (profile) is never restored from legacy JSON through PINE: it
# bootstraps via the local section-1 patch and the client's native autosave.
LEGACY_PROFILE_FILE = "profile.json"


class ObjectState(str, Enum):
    """Per-type migration states from notes/07 phase 1."""

    NOT_NEEDED = "not_needed"
    PENDING = "pending"
    RESTORED = "restored"
    CAPTURED = "captured"
    COMPLETE = "complete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class NativeObjectInfo:
    type_id: int
    expected_size: int


# Exact sizes validated by the v0.4.0 release regression.
NATIVE_OBJECTS = {
    0x80000001: NativeObjectInfo(0x80000001, 0x1238),
    0x80000002: NativeObjectInfo(0x80000002, 0x1804),
    0x80000003: NativeObjectInfo(0x80000003, 0x53C4),
}


def native_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class TypeAssessment:
    type_id: int
    state: ObjectState
    legacy_source: Path | None = None
    native_path: Path | None = None
    native_size: int | None = None
    native_sha256: str | None = None
    detail: str = ""

    @property
    def eligible_for_restore(self) -> bool:
        return self.state is ObjectState.PENDING


@dataclass
class InstallationReport:
    assessments: dict[int, TypeAssessment] = field(default_factory=dict)
    marker: dict | None = None
    backup_path: Path | None = None

    @property
    def migration_needed(self) -> bool:
        return any(a.state is ObjectState.PENDING
                   for a in self.assessments.values())

    @property
    def blocked(self) -> bool:
        return any(a.state is ObjectState.BLOCKED
                   for a in self.assessments.values())

    @property
    def pending_types(self) -> list[int]:
        return sorted(a.type_id for a in self.assessments.values()
                      if a.state is ObjectState.PENDING)


@dataclass(frozen=True)
class UploadDecision:
    allowed: bool
    retryable: bool = False
    state: str = ""
    reason: str = ""


class UploadGate:
    """Thread-safe migration-aware gate for native UserStorage uploads.

    The Phase 3 wiring: the HTTP handler calls check() before storing a PUT
    and record_stored() only after the atomic replace has succeeded, so an
    object reaches CAPTURED only when an exact-size body is durably in the
    authoritative user-content directory.

    Rules while a gate is active (a fresh/completed install never installs
    one and keeps the v0.4.0 accept-anything behavior):

    - Every upload must match the exact expected native size; a valid native
      file is never replaced by an invalid-length body.
    - A type-2/type-3 PUT whose migration state is still PENDING (the legacy
      object has not been restored into live memory yet) is deferred with a
      retryable result, so the client's fallback autosave cannot become
      authoritative. Whether the client retries this safely is confirmed in
      the Phase 5 live test.
    - Type 1 is never PINE-restored, so it is accepted regardless of state
      (subject to the exact-size rule) and its upload is what completes it.
    """

    def __init__(self, expected_sizes: dict[int, int] | None = None,
                 states: dict[int, ObjectState] | None = None):
        self._lock = threading.Lock()
        self._expected = dict(expected_sizes or
                              {t: i.expected_size
                               for t, i in NATIVE_OBJECTS.items()})
        self._states = dict(states or {})

    def set_state(self, type_id: int, state: ObjectState) -> None:
        with self._lock:
            self._states[type_id] = state

    def state(self, type_id: int) -> ObjectState:
        with self._lock:
            return self._states.get(type_id, ObjectState.NOT_NEEDED)

    def check(self, type_id: int, length: int) -> UploadDecision:
        """Decide one upload. Called before the body is stored."""
        with self._lock:
            state = self._states.get(type_id, ObjectState.NOT_NEEDED)
            expected = self._expected.get(type_id)
        if expected is None:
            return UploadDecision(
                False, False, state.value,
                f"unknown native type 0x{type_id:08X}")
        if length != expected:
            return UploadDecision(
                False, False, state.value,
                f"invalid length {length} for type 0x{type_id:08X}; "
                f"expected exactly {expected}")
        if state is ObjectState.BLOCKED:
            return UploadDecision(
                False, False, state.value,
                f"type 0x{type_id:08X} is blocked by a malformed native "
                "object; recovery is required before uploads are accepted")
        if (state is ObjectState.PENDING and type_id != 0x80000001):
            return UploadDecision(
                False, True, state.value,
                f"type 0x{type_id:08X} is pending legacy restore; "
                "deferring the fallback upload")
        return UploadDecision(True, False, state.value, "accepted")

    def record_stored(self, type_id: int, length: int) -> ObjectState:
        """Record a durably stored upload; pending types become captured."""
        with self._lock:
            state = self._states.get(type_id, ObjectState.NOT_NEEDED)
            if state in (ObjectState.PENDING, ObjectState.RESTORED):
                state = ObjectState.CAPTURED
                self._states[type_id] = state
            return state

    @classmethod
    def from_report(cls, report: InstallationReport) -> "UploadGate":
        """Build the gate for a migration run: pending types start deferred."""
        states = {type_id: a.state
                  for type_id, a in report.assessments.items()}
        return cls(states=states)


def marker_path(data_dir: Path) -> Path:
    return Path(data_dir) / MIGRATION_MARKER_NAME


def read_marker(data_dir: Path) -> dict | None:
    """Return the parsed migration marker, or None when absent/unreadable."""
    path = marker_path(data_dir)
    if not path.is_file():
        return None
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) else None


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_marker(data_dir: Path, marker: dict) -> None:
    _write_atomic(marker_path(data_dir),
                  json.dumps(marker, indent=2, sort_keys=True))


def _valid_legacy_json(data_dir: Path, file_name: str,
                       required_key: str) -> bool:
    path = Path(data_dir) / file_name
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(data, dict)
            and "schema_version" in data
            and required_key in data)


def evaluate_installation(data_dir: Path) -> InstallationReport:
    """Read-only detection of legacy/native state for all three types."""
    data_dir = Path(data_dir)
    report = InstallationReport(marker=read_marker(data_dir))

    # A completed marker means migration already finished; never re-run it.
    if report.marker is not None \
            and report.marker.get("status") == "complete":
        for info in NATIVE_OBJECTS.values():
            report.assessments[info.type_id] = TypeAssessment(
                info.type_id, ObjectState.NOT_NEEDED,
                detail="migration marker reports complete")
        return report

    # Resume support: a pending marker keeps its recorded backup so the
    # rollback copy is never weakened or duplicated.
    marker_backup = None
    if report.marker is not None:
        raw = report.marker.get("backup_path")
        if isinstance(raw, str):
            candidate = Path(raw)
            if candidate.is_dir():
                marker_backup = candidate
    report.backup_path = marker_backup

    for type_id, info in NATIVE_OBJECTS.items():
        native_path = (data_dir / "usercontent" / f"{type_id:08x}" /
                       f"{NATIVE_CONTENT_ID}.bin")
        if native_path.is_file():
            size = native_path.stat().st_size
            if size == info.expected_size:
                report.assessments[type_id] = TypeAssessment(
                    type_id, ObjectState.NOT_NEEDED,
                    native_path=native_path, native_size=size,
                    native_sha256=native_sha256(native_path),
                    detail="valid native object")
            else:
                report.assessments[type_id] = TypeAssessment(
                    type_id, ObjectState.BLOCKED,
                    native_path=native_path, native_size=size,
                    detail=f"malformed native object: expected "
                           f"{info.expected_size} bytes, found {size}; "
                           f"recovery condition, not treated as absent")
            continue

        legacy = LEGACY_FILES.get(type_id)
        if legacy is None:
            # Type 1: no PINE restore; the local section-1 patch plus the
            # client's native autosave cover it. A legacy economy profile
            # keeps the type pending so its native capture is tracked.
            legacy_file = data_dir / LEGACY_PROFILE_FILE
            report.assessments[type_id] = TypeAssessment(
                type_id,
                ObjectState.PENDING if legacy_file.is_file()
                else ObjectState.NOT_NEEDED,
                legacy_source=legacy_file if legacy_file.is_file() else None,
                detail="profile native object absent; "
                       "bootstrap via local patch and native autosave"
                if legacy_file.is_file()
                else "no native object and no legacy profile")
            continue

        legacy_file = data_dir / legacy[0]
        if _valid_legacy_json(data_dir, legacy[0], legacy[1]):
            report.assessments[type_id] = TypeAssessment(
                type_id, ObjectState.PENDING,
                legacy_source=legacy_file,
                detail="valid legacy JSON with no native counterpart")
        else:
            report.assessments[type_id] = TypeAssessment(
                type_id, ObjectState.NOT_NEEDED,
                detail="no native object and no valid legacy JSON")

    return report


def create_backup(data_dir: Path, report: InstallationReport | None = None
                  ) -> Path:
    """Timestamped copy of the complete active data directory.

    The backup lives beside (never inside) data_dir so it cannot nest into
    itself and stays out of the active save path. If a pending migration
    marker already records a usable backup, that backup is reused.
    """
    data_dir = Path(data_dir)
    if report is not None and report.backup_path is not None:
        return report.backup_path

    timestamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = data_dir.parent / BACKUP_DIR_NAME
    backup = backup_root / f"data-{timestamp}"
    counter = 0
    while backup.exists():
        counter += 1
        backup = backup_root / f"data-{timestamp}-{counter}"
    if data_dir.is_dir():
        shutil.copytree(data_dir, backup)
    else:
        backup.mkdir(parents=True, exist_ok=True)
    return backup


def build_marker(data_dir: Path, report: InstallationReport,
                 backup_path: Path, status: str) -> dict:
    """Assemble the auditable completion/progress marker contents."""
    data_dir = Path(data_dir)
    objects = {}
    for type_id in sorted(report.assessments):
        assessment = report.assessments[type_id]
        native = NATIVE_OBJECTS[type_id]
        entry = {
            "state": assessment.state.value,
            "expected_size": native.expected_size,
        }
        if assessment.legacy_source is not None:
            entry["legacy_source"] = str(
                assessment.legacy_source.relative_to(data_dir.parent)
                if assessment.legacy_source.is_relative_to(data_dir.parent)
                else assessment.legacy_source)
        if assessment.native_size is not None:
            entry["native_size"] = assessment.native_size
        if assessment.native_sha256 is not None:
            entry["native_sha256"] = assessment.native_sha256
        objects[f"0x{type_id:08X}"] = entry
    return {
        "status": status,
        "backup_path": str(backup_path),
        "objects": objects,
        "updated_at": _datetime.datetime.now().isoformat(
            timespec="seconds"),
    }
