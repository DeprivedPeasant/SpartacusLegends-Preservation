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


class TitleVersion(str, Enum):
    """Supported Spartacus Legends builds (PARAM.SFO APP_VER)."""

    V100 = "01.00"
    V106 = "01.06"


DEFAULT_TITLE_VERSION = TitleVersion.V100

# PPU hashes RPCS3 reports for each supported build. Used for documentation
# and for matching the distributed patch YAML; the server never computes them.
PPU_HASHES = {
    TitleVersion.V100: "81471d050c14f4d20b4027686f8b571dafd32394",
    TitleVersion.V106: "131aece6ae8526d13307be925f48c87f73c43799",
}


@dataclass(frozen=True)
class NativeObjectInfo:
    """One native UserStorage object type for one title version.

    ``expected_size`` is the size that build's writer produces and the size
    the marker records. ``accepted_sizes`` is every size that build's
    size-validation dispatcher admits, which for 01.06 includes the older
    01.00 layouts it reads forward.
    """

    type_id: int
    expected_size: int
    accepted_sizes: tuple[int, ...]

    def accepts(self, size: int) -> bool:
        return size in self.accepted_sizes


def _objects(profile, campaign, roster) -> dict:
    rows = ((0x80000001, profile), (0x80000002, campaign),
            (0x80000003, roster))
    return {type_id: NativeObjectInfo(type_id, sizes[0], tuple(sizes))
            for type_id, sizes in rows}


# 01.00 sizes were validated by the v0.4.0 release regression. The 01.06
# sizes come from that build's size-validation dispatcher
# (0x00155000-0x00157400); see notes/13-v106-port.md.
NATIVE_OBJECTS_BY_VERSION = {
    TitleVersion.V100: _objects((0x1238,), (0x1804,), (0x53C4,)),
    TitleVersion.V106: _objects((0x15B8, 0x1590, 0x1238),
                                (0x1C04,),
                                (0x53C8, 0x53C4)),
}

# Backwards-compatible default view for callers that predate multi-version
# support. Prefer native_objects(title_version).
NATIVE_OBJECTS = NATIVE_OBJECTS_BY_VERSION[DEFAULT_TITLE_VERSION]


def coerce_title_version(value) -> TitleVersion:
    """Accept a TitleVersion, "01.06", or "1.06" and return the enum."""
    if isinstance(value, TitleVersion):
        return value
    if value is None:
        return DEFAULT_TITLE_VERSION
    text = str(value).strip()
    for candidate in TitleVersion:
        if text == candidate.value or text == candidate.value.lstrip("0"):
            return candidate
    raise ValueError(f"unsupported title version {value!r}; "
                     f"supported: {[v.value for v in TitleVersion]}")


def native_objects(title_version=DEFAULT_TITLE_VERSION) -> dict:
    """Native object table for one supported build."""
    return NATIVE_OBJECTS_BY_VERSION[coerce_title_version(title_version)]


def native_content_dir(data_dir: Path,
                       title_version=DEFAULT_TITLE_VERSION) -> Path:
    """Authoritative UserStorage root for one build.

    The shipped 01.00 location remains unchanged for backward compatibility.
    Newer incompatible layouts live beneath a version namespace, so changing
    the installed title can never replace another build's campaign object.
    """
    version = coerce_title_version(title_version)
    root = Path(data_dir) / "usercontent"
    return root if version is TitleVersion.V100 else root / version.value


def _size_text(info: NativeObjectInfo) -> str:
    if len(info.accepted_sizes) == 1:
        return f"{info.expected_size} bytes"
    return ("one of " + ", ".join(str(s) for s in info.accepted_sizes)
            + " bytes")


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
    title_version: "TitleVersion" = DEFAULT_TITLE_VERSION

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
                 states: dict[int, ObjectState] | None = None,
                 title_version=DEFAULT_TITLE_VERSION):
        self._lock = threading.Lock()
        self.title_version = coerce_title_version(title_version)
        objects = native_objects(self.title_version)
        if expected_sizes is None:
            self._accepted = {t: i.accepted_sizes for t, i in objects.items()}
        else:
            # An explicit override stays exact-size, as before.
            self._accepted = {t: (size,)
                              for t, size in expected_sizes.items()}
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
            accepted = self._accepted.get(type_id)
        if accepted is None:
            return UploadDecision(
                False, False, state.value,
                f"unknown native type 0x{type_id:08X}")
        if length not in accepted:
            wanted = (f"exactly {accepted[0]}" if len(accepted) == 1
                      else "one of " + ", ".join(str(s) for s in accepted))
            return UploadDecision(
                False, False, state.value,
                f"invalid length {length} for type 0x{type_id:08X}; "
                f"expected {wanted}")
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
        return cls(states=states, title_version=report.title_version)


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


def evaluate_installation(data_dir: Path,
                          title_version=DEFAULT_TITLE_VERSION
                          ) -> InstallationReport:
    """Read-only detection of legacy/native state for all three types."""
    data_dir = Path(data_dir)
    title_version = coerce_title_version(title_version)
    objects = native_objects(title_version)
    report = InstallationReport(marker=read_marker(data_dir),
                                title_version=title_version)

    # A completed marker means migration already finished; never re-run it.
    if report.marker is not None \
            and report.marker.get("status") == "complete":
        for info in objects.values():
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

    for type_id, info in objects.items():
        native_path = (native_content_dir(data_dir, title_version) /
                       f"{type_id:08x}" /
                       f"{NATIVE_CONTENT_ID}.bin")
        if native_path.is_file():
            size = native_path.stat().st_size
            if info.accepts(size):
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
                           f"{_size_text(info)}, found {size}; "
                           f"recovery condition, not treated as absent")
            continue

        # Legacy JSON/PINE captures were produced by 01.00 and its restore
        # bridge verifies that exact build. Never reinterpret them as 01.06
        # native state; a new 01.06 namespace starts clean instead.
        if title_version is not TitleVersion.V100:
            report.assessments[type_id] = TypeAssessment(
                type_id, ObjectState.NOT_NEEDED,
                detail="legacy JSON migration applies only to title 01.00")
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
    table = native_objects(report.title_version)
    objects = {}
    for type_id in sorted(report.assessments):
        assessment = report.assessments[type_id]
        native = table[type_id]
        entry = {
            "state": assessment.state.value,
            "expected_size": native.expected_size,
        }
        if len(native.accepted_sizes) > 1:
            entry["accepted_sizes"] = list(native.accepted_sizes)
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
        "title_version": report.title_version.value,
        "backup_path": str(backup_path),
        "objects": objects,
        "updated_at": _datetime.datetime.now().isoformat(
            timespec="seconds"),
    }
