#!/usr/bin/env python3
"""Configure RPCS3 for the Spartacus Legends preservation server."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

try:
    from server_config import (
        config_path as server_config_path,
        encode_title_version,
        read_title_version,
    )
except ImportError:  # Imported as tools.patch_installer by the unit tests.
    from tools.server_config import (
        config_path as server_config_path,
        encode_title_version,
        read_title_version,
    )

try:
    import adaptive_patch
    import eboot_source
    import ppu_hash
except ImportError:  # Imported as tools.patch_installer by the unit tests.
    from tools import adaptive_patch, eboot_source, ppu_hash


# Every supported build, keyed by PARAM.SFO APP_VER. RPCS3 selects a patch
# section by the running executable's PPU hash, so both sections are always
# installed and enabled; only the matching one applies.
SUPPORTED_BUILDS = {
    "01.00": "PPU-81471d050c14f4d20b4027686f8b571dafd32394:",
    "01.06": "PPU-131aece6ae8526d13307be925f48c87f73c43799:",
}
TITLE_ID = "NPUB30746"
GAME_VERSION = "01.00"
PPU_HEADER = SUPPORTED_BUILDS[GAME_VERSION]
IP_SWAP = "onlineconfigservice.ubi.com=127.0.0.1"
COMPATIBILITY_PATCH = "Spartacus Legends - Server emulator compatibility"
MATCHMAKING_PATCH = "Spartacus Legends - Online matchmaking compatibility (experimental)"
PROJECT_PATCHES = (
    f'  "{COMPATIBILITY_PATCH}":',
    f'  "{MATCHMAKING_PATCH}":',
    '  "Spartacus Legends - One-hit fight debug cheat (optional)":',
    '  "Spartacus Legends - Skip startup logo screens (optional)":',
)


@dataclass(frozen=True)
class InstallResult:
    imported_patch: Path
    custom_config: Path
    patch_config: Path
    server_config: Path
    title_version: str | None
    backups: tuple[Path, ...]
    cache_cleared: bool
    adaptive_hash: str | None = None
    adaptive_report: Path | None = None
    # False when the game version could not be detected and no version was
    # given: server-config.json is then left exactly as it was.
    server_config_written: bool = True


class UnusedRPCS3FolderError(ValueError):
    """The chosen RPCS3 has never been used to play the game."""


class InstallWriteError(OSError):
    """Windows refused a write; ``rolled_back`` says whether nothing changed."""

    def __init__(self, message: str, rolled_back: bool):
        super().__init__(message)
        self.rolled_back = rolled_back


# Windows mandatory integrity levels (the RID of the token's label SID).
INTEGRITY_LOW = 0x1000
INTEGRITY_MEDIUM = 0x2000

LOW_INTEGRITY_HELP = (
    "This program is running at Windows' Low integrity level, so Windows "
    "blocks it from changing RPCS3's settings and your saves even though the "
    "folders allow it. That happens when the folder it was started from has "
    "a Low integrity label - some sandboxing tools add one to folders they "
    "work in. Copy the whole release folder somewhere ordinary (for example "
    "your Desktop or Documents) and start it from there.")


def process_integrity_level() -> int | None:
    """This process's mandatory integrity RID on Windows, else None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD)]
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(
            ctypes.c_ubyte)
        advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
        advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p,
                                                wintypes.DWORD]
        token = wintypes.HANDLE()
        token_query = 0x0008
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                         token_query, ctypes.byref(token)):
            return None
        try:
            token_integrity_level = 25
            needed = wintypes.DWORD()
            advapi32.GetTokenInformation(token, token_integrity_level, None,
                                         0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi32.GetTokenInformation(
                    token, token_integrity_level, buffer, needed,
                    ctypes.byref(needed)):
                return None
            # TOKEN_MANDATORY_LABEL starts with a SID_AND_ATTRIBUTES whose
            # first member is the label SID pointer.
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            count = advapi32.GetSidSubAuthorityCount(sid)[0]
            return int(advapi32.GetSidSubAuthority(sid, count - 1)[0])
        finally:
            kernel32.CloseHandle(token)
    except (OSError, AttributeError, ValueError):
        return None


def low_integrity_problem() -> str | None:
    """The plain explanation when this process runs at Low integrity."""
    level = process_integrity_level()
    if level is not None and level < INTEGRITY_MEDIUM:
        return LOW_INTEGRITY_HELP
    return None


WRITE_BLOCKED_HELP = (
    "Windows refused to let this program create files there, although the "
    "folder's own permissions may allow it. Common causes: the program was "
    "started from a sandboxed terminal or tool (start it by double-clicking "
    "it in File Explorer instead), security software blocking an "
    "unrecognised program (allow it), or a folder that needs administrator "
    "rights (run it as administrator once).")


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def supplied_patch_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "SpartacusLegends_ServerPatch.yml"
    return application_dir() / "packaging" / "SpartacusLegends_ServerPatch.yml"


def supplied_signature_path() -> Path:
    """The generated signature database, bundled beside the installer exe."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "patch_signatures.json"
    return application_dir() / "tools" / "patch_signatures.json"


def _adaptive_section(title_version: str, eboot: Path, root: Path,
                      allow_decrypt: bool,
                      imported_contents: str,
                      patch_contents: str
                      ) -> tuple[str, str, str | None, dict | None]:
    """Generate and merge the user's-hash section, or leave install unchanged.

    Returns ``(imported_contents, patch_contents, user_hash, report)``. A known
    PPU hash returns the inputs untouched: the distributed section already
    covers it, so adaptive mode changes nothing.
    """
    database_path = supplied_signature_path()
    if not database_path.is_file():
        raise FileNotFoundError(
            f"Signature database is missing: {database_path}")
    with eboot_source.open_eboot(
            eboot, root, allow_decrypt=allow_decrypt) as elf_bytes:
        user_hash = ppu_hash.ppu_hash(elf_bytes)
        if f"{user_hash}:" in SUPPORTED_BUILDS.values():
            return imported_contents, patch_contents, user_hash, None
        database = adaptive_patch.load_signature_database(database_path)
        patch_set = database["builds"].get(title_version)
        if patch_set is None:
            raise ValueError(
                f"no signature set for game version {title_version}")
        resolved = adaptive_patch.resolve(elf_bytes, patch_set)
        section = adaptive_patch.render_section(user_hash, resolved)
        report = adaptive_patch.report_json(
            user_hash, resolved,
            reference_hash=database["generated_from"]
            .get(title_version, {}).get("ppu_hash"),
        )
    header = user_hash + ":"
    merged_imported = _merge_one_section(
        imported_contents.splitlines(), section, header)
    merged_patch_config = _enable_in_section(
        patch_contents.splitlines(), header, title_version)
    return (
        "\n".join(merged_imported).rstrip() + "\n",
        "\n".join(merged_patch_config).rstrip() + "\n",
        user_hash,
        report,
    )


def ppu_block_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if lines[index] and not lines[index].startswith((" ", "\t")):
            return index
    return len(lines)


def remove_project_patches(lines: list[str], ppu_header: str = PPU_HEADER
                           ) -> tuple[list[str], bool]:
    """Remove just this project's named entries from its PPU section."""
    try:
        section_start = lines.index(ppu_header)
    except ValueError:
        return lines, False

    section_end = ppu_block_end(lines, section_start)
    result = lines[:section_start + 1]
    index = section_start + 1
    while index < section_end:
        if lines[index] in PROJECT_PATCHES:
            index += 1
            while index < section_end and not lines[index].startswith('  "'):
                index += 1
            continue
        result.append(lines[index])
        index += 1
    result.extend(lines[section_end:])
    return result, True


def supplied_entries(template: str, ppu_header: str = PPU_HEADER
                     ) -> list[str]:
    lines = template.splitlines()
    if ppu_header not in lines:
        return []
    start = lines.index(ppu_header) + 1
    return lines[start:ppu_block_end(lines, start - 1)]


def _merge_one_section(existing_lines: list[str], template: str,
                       ppu_header: str) -> list[str]:
    remaining, found = remove_project_patches(existing_lines, ppu_header)
    entries = supplied_entries(template, ppu_header)
    while entries and not entries[0].strip():
        entries.pop(0)
    while entries and not entries[-1].strip():
        entries.pop()
    if not entries:
        return remaining
    if found:
        # Stay inside this PPU section: a later section's entries must never
        # be treated as this one's insertion point.
        section_start = remaining.index(ppu_header)
        section_end = ppu_block_end(remaining, section_start)
        insert_at = section_start + 1
        while (insert_at < section_end
               and not remaining[insert_at].startswith('  "')):
            insert_at += 1
        # Collapse any blank run left behind by a previous merge so repeated
        # installs are idempotent.
        while (insert_at > section_start + 1
               and not remaining[insert_at - 1].strip()):
            insert_at -= 1
        tail = remaining[insert_at:]
        while tail and not tail[0].strip():
            tail.pop(0)
        return (remaining[:insert_at] + [""] + entries
                + ([""] + tail if tail else []))
    return (remaining + ([""] if remaining[-1:] != [""] else [])
            + [ppu_header, ""] + entries)


def merge_patch(existing: str, template: str) -> str:
    """Merge project entries while retaining every other imported RPCS3 patch."""
    existing_lines = existing.splitlines()
    if existing_lines and existing_lines[0].startswith("\ufeff"):
        existing_lines[0] = existing_lines[0].lstrip("\ufeff")
    if not existing_lines:
        existing_lines = ["Version: 1.2", ""]
    if not existing_lines[0].startswith("Version:"):
        raise ValueError("imported_patch.yml does not begin with a Version header")

    merged = existing_lines
    for ppu_header in SUPPORTED_BUILDS.values():
        merged = _merge_one_section(merged, template, ppu_header)
    return "\n".join(merged).rstrip() + "\n"


def find_target(folder: Path) -> Path:
    folder = folder.expanduser().resolve()
    if folder.name.lower() == "patches":
        return folder / "imported_patch.yml"
    return folder / "patches" / "imported_patch.yml"


def find_rpcs3_root(folder: Path) -> Path:
    folder = folder.expanduser().resolve()
    if folder.name.lower() == "patches":
        folder = folder.parent
    if not (folder / "patches").is_dir() or not (folder / "config").is_dir():
        raise FileNotFoundError(
            f"Could not find RPCS3's patches and config folders in: {folder}\n"
            "Choose the folder containing rpcs3.exe."
        )
    return folder


def merge_section_settings(existing: str, section: str,
                           settings: dict[str, str]) -> str:
    """Set direct children of one top-level RPCS3 YAML section."""
    lines = existing.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    try:
        start = lines.index(f"{section}:")
    except ValueError:
        if lines and lines[-1]:
            lines.append("")
        lines.append(f"{section}:")
        lines.extend(f"  {key}: {value}" for key, value in settings.items())
        return "\n".join(lines).rstrip() + "\n"

    end = ppu_block_end(lines, start)
    found: set[str] = set()
    for index in range(start + 1, end):
        for key, value in settings.items():
            if lines[index].startswith(f"  {key}:"):
                lines[index] = f"  {key}: {value}"
                found.add(key)
                break
    additions = [f"  {key}: {value}" for key, value in settings.items()
                 if key not in found]
    lines[end:end] = additions
    return "\n".join(lines).rstrip() + "\n"


def _enable_in_section(lines: list[str], ppu_header: str,
                       version: str) -> list[str]:
    try:
        section_start = lines.index(ppu_header)
        section_end = ppu_block_end(lines, section_start)
    except ValueError:
        if lines and lines[-1]:
            lines.append("")
        section_start = len(lines)
        lines.append(ppu_header)
        section_end = len(lines)

    index = section_start + 1
    while index < section_end:
        patch_line = lines[index].strip()
        if (len(lines[index]) - len(lines[index].lstrip()) == 2 and
                patch_line in {f"{COMPATIBILITY_PATCH}:",
                               f'"{COMPATIBILITY_PATCH}":'}):
            remove_end = index + 1
            while remove_end < section_end:
                indent = len(lines[remove_end]) - len(lines[remove_end].lstrip())
                if lines[remove_end].strip() and indent <= 2:
                    break
                remove_end += 1
            # Keep the blank line that separates this PPU section from the
            # next one so repeated installs stay idempotent.
            while remove_end > index + 1 and not lines[remove_end - 1].strip():
                remove_end -= 1
            del lines[index:remove_end]
            section_end -= remove_end - index
            continue
        index += 1

    block = [
        f"  {COMPATIBILITY_PATCH}:",
        "    Spartacus Legends:",
        f"      {TITLE_ID}:",
        f"        {version}:",
        "          Enabled: true",
    ]
    lines[section_start + 1:section_start + 1] = block
    return lines


def merge_patch_config(existing: str) -> str:
    """Enable the required compatibility patch for every supported build."""
    lines = existing.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    # RPCS3 writes a lone "{}" document for an empty patch_config.yml.
    # Appending block mappings after it would not parse.
    if [line for line in lines if line.strip()] == ["{}"]:
        lines = []
    for version, ppu_header in SUPPORTED_BUILDS.items():
        lines = _enable_in_section(lines, ppu_header, version)
    return "\n".join(lines).rstrip() + "\n"


def backup_and_write(path: Path, contents: str, stamp: str,
                     backups: list[Path],
                     journal: list | None = None) -> None:
    """Back up ``path`` and write ``contents``, recording undo information.

    ``journal`` receives ``(path, backup_or_None)`` before the file changes,
    so a failure later in the install can restore it.
    """
    current = path.read_text(encoding="utf-8-sig") if path.exists() else None
    if current == contents:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        suffix = 1
        while backup.exists():
            backup = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
            suffix += 1
        shutil.copy2(path, backup)
        backups.append(backup)
    if journal is not None:
        journal.append((path, backup))
    path.write_text(contents, encoding="utf-8", newline="\n")


def _existing_ancestor(path: Path) -> Path:
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def write_access_problem(directories) -> str | None:
    """Try to create and delete a probe file in each folder; describe refusals.

    Missing folders are probed at their nearest existing parent, which is
    where they would be created. Nothing is left behind.
    """
    refused = []
    seen = set()
    for directory in directories:
        target = _existing_ancestor(Path(directory))
        key = str(target).lower()
        if key in seen:
            continue
        seen.add(key)
        probe = target / f"~spartacus-write-check-{os.getpid()}.tmp"
        try:
            probe.write_bytes(b"")
        except OSError as error:
            refused.append(f"{target} ({error.strerror or error})")
            continue
        try:
            probe.unlink()
        except OSError:
            pass
    if not refused:
        return None
    return ("Nothing was changed. Could not write to: " + "; ".join(refused)
            + ". " + (low_integrity_problem() or WRITE_BLOCKED_HELP))


def _roll_back(journal: list) -> list[str]:
    """Undo journalled writes, newest first; return what could not be undone."""
    failures = []
    for path, backup in reversed(journal):
        try:
            if backup is not None:
                shutil.copy2(backup, path)
            elif path.exists():
                path.unlink()
        except OSError as error:
            failures.append(f"{path} ({error})")
            continue
        if backup is not None:
            try:
                backup.unlink()  # identical to the restored file now
            except OSError:
                pass
    return failures


def install_patch(rpcs3_folder: Path) -> tuple[Path, Path | None]:
    template_path = supplied_patch_path()
    if not template_path.is_file():
        raise FileNotFoundError(f"Supplied patch file is missing: {template_path}")
    target = find_target(rpcs3_folder)
    if not target.parent.is_dir():
        raise FileNotFoundError(
            f"Could not find RPCS3's patches folder: {target.parent}\n"
            "Choose the RPCS3 folder, not its dev_hdd0 folder."
        )
    existing = target.read_text(encoding="utf-8-sig") if target.exists() else ""
    merged = merge_patch(existing, template_path.read_text(encoding="utf-8"))
    backup = None
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_name(f"imported_patch.yml.{stamp}.bak")
        shutil.copy2(target, backup)
    target.write_text(merged, encoding="utf-8", newline="\n")
    return target, backup


def install_setup(rpcs3_folder: Path,
                  server_base_dir: Path | None = None, *,
                  eboot: Path | None = None,
                  adaptive: bool = False,
                  allow_decrypt: bool = False,
                  allow_unused_folder: bool = False,
                  title_version: str | None = None) -> InstallResult:
    """Write the patch, network and server configuration.

    Refuses (before reading or writing anything else) a folder that has
    neither the game nor an RPCN account unless ``allow_unused_folder``.
    ``title_version`` overrides detection; when neither is available the
    server's ``server-config.json`` is left unchanged.
    """
    root = find_rpcs3_root(rpcs3_folder)
    if not allow_unused_folder:
        problem = unused_folder_problem(root)
        if problem:
            raise UnusedRPCS3FolderError(problem)
    server_base_dir = (application_dir() if server_base_dir is None
                       else Path(server_base_dir))
    if title_version is not None and title_version not in SUPPORTED_BUILDS:
        raise ValueError(f"unsupported game version {title_version!r}")
    title_version = title_version or detected_game_version(root)
    template_path = supplied_patch_path()
    if not template_path.is_file():
        raise FileNotFoundError(f"Supplied patch file is missing: {template_path}")
    if adaptive and eboot is None:
        raise ValueError(
            "--adaptive needs --eboot (encrypted EBOOT.BIN) or --eboot-elf "
            "(already decrypted ELF)")

    imported_patch = root / "patches" / "imported_patch.yml"
    imported_existing = (imported_patch.read_text(encoding="utf-8-sig")
                         if imported_patch.exists() else "")
    imported_contents = merge_patch(
        imported_existing, template_path.read_text(encoding="utf-8"))

    custom_config = root / "config" / "custom_configs" / f"config_{TITLE_ID}.yml"
    if custom_config.exists():
        custom_existing = custom_config.read_text(encoding="utf-8-sig")
    else:
        global_config = root / "config" / "config.yml"
        if not global_config.is_file():
            raise FileNotFoundError(f"Could not find RPCS3's base config: {global_config}")
        custom_existing = global_config.read_text(encoding="utf-8-sig")
    custom_contents = merge_section_settings(custom_existing, "Net", {
        "IP swap list": IP_SWAP,
        "Internet enabled": "Connected",
        "PSN status": "RPCN",
    })

    patch_config = root / "config" / "patch_config.yml"
    patch_existing = (patch_config.read_text(encoding="utf-8-sig")
                      if patch_config.exists() else "")
    patch_contents = merge_patch_config(patch_existing)
    server_config = server_config_path(server_base_dir)
    server_config_contents = (encode_title_version(title_version)
                              if title_version is not None else None)
    if adaptive and title_version is None:
        raise ValueError(
            "the game version could not be detected, so no signature set "
            "can be chosen for an adaptive patch")

    adaptive_hash = None
    adaptive_report = None
    report = None
    if adaptive:
        imported_contents, patch_contents, adaptive_hash, report = \
            _adaptive_section(
                title_version, Path(eboot), root, allow_decrypt,
                imported_contents, patch_contents)
        if report is not None:
            adaptive_report = (root / "patches" /
                               f"adaptive-patch-{adaptive_hash}-report.json")

    targets = [imported_patch, custom_config, patch_config]
    if server_config_contents is not None:
        targets.append(server_config)
    problem = write_access_problem(path.parent for path in targets)
    if problem:
        raise InstallWriteError(problem, rolled_back=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    journal: list = []
    try:
        backup_and_write(imported_patch, imported_contents, stamp, backups,
                         journal)
        backup_and_write(custom_config, custom_contents, stamp, backups,
                         journal)
        backup_and_write(patch_config, patch_contents, stamp, backups,
                         journal)
        if server_config_contents is not None:
            backup_and_write(server_config, server_config_contents, stamp,
                             backups, journal)
    except OSError as error:
        unrestored = _roll_back(journal)
        if unrestored:
            raise InstallWriteError(
                f"The install stopped part-way: {error}. These files could "
                "not be put back and still hold the new settings (their "
                "backups sit beside them): " + "; ".join(unrestored),
                rolled_back=False) from error
        raise InstallWriteError(
            f"The install stopped: {error}. Every file it had already "
            "changed was put back, so nothing was changed. "
            + (low_integrity_problem() or WRITE_BLOCKED_HELP),
            rolled_back=True) from error
    if adaptive_report is not None and report is not None:
        # Written only after the patch files are in place; a fixed name keeps
        # a re-run idempotent instead of accumulating timestamped reports.
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        current = (adaptive_report.read_text(encoding="utf-8")
                   if adaptive_report.is_file() else None)
        if current != rendered:
            adaptive_report.write_text(
                rendered, encoding="utf-8", newline="\n")

    cache = root / "cache" / TITLE_ID
    cache_cleared = cache.exists()
    if cache_cleared:
        shutil.rmtree(cache)

    return InstallResult(imported_patch, custom_config, patch_config,
                         server_config, title_version, tuple(backups),
                         cache_cleared, adaptive_hash, adaptive_report,
                         server_config_written=server_config_contents
                         is not None)


def read_param_sfo(path: Path) -> dict[str, str]:
    """Read the string fields of a PS3 PARAM.SFO (enough for TITLE_ID/APP_VER)."""
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"\x00PSF":
        raise ValueError(f"Not a PARAM.SFO file: {path}")
    key_table = int.from_bytes(data[8:12], "little")
    data_table = int.from_bytes(data[12:16], "little")
    entries = int.from_bytes(data[16:20], "little")
    fields: dict[str, str] = {}
    for index in range(entries):
        entry = 20 + index * 16
        if entry + 16 > len(data):
            break
        key_offset = int.from_bytes(data[entry:entry + 2], "little")
        data_format = int.from_bytes(data[entry + 2:entry + 4], "little")
        data_length = int.from_bytes(data[entry + 4:entry + 8], "little")
        data_offset = int.from_bytes(data[entry + 12:entry + 16], "little")
        key_start = key_table + key_offset
        key_end = data.find(b"\x00", key_start)
        if key_end < 0:
            break
        key = data[key_start:key_end].decode("utf-8", "replace")
        if data_format in (0x0204, 0x0004):  # UTF-8 string
            raw = data[data_table + data_offset:data_table + data_offset + data_length]
            fields[key] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return fields


def games_config_paths(root: Path) -> list[Path]:
    """Paths RPCS3's games.yml records for the supported title."""
    paths: list[Path] = []
    for games_yml in (root / "config" / "games.yml", root / "games.yml"):
        if not games_yml.is_file():
            continue
        for line in games_yml.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if not separator or key.strip().strip('"\'') != TITLE_ID:
                continue
            value = value.strip().strip('"\'')
            if value:
                paths.append(Path(value))
    return paths


def _vfs_entries(root: Path) -> dict[str, str]:
    """Top-level ``key: value`` pairs of RPCS3's vfs.yml, if it has one."""
    entries: dict[str, str] = {}
    for vfs in (root / "config" / "vfs.yml", root / "vfs.yml"):
        if not vfs.is_file():
            continue
        try:
            text = vfs.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if not line or line[0].isspace() or line.lstrip().startswith("#"):
                continue
            # Keys such as "/dev_hdd0/" and "$(EmulatorDir)" contain no ": ".
            key, separator, value = line.partition(": ")
            if not separator:
                key, separator, value = line.rstrip().partition(":")
                if not separator or value:
                    continue
            entries[key.strip().strip('"\'')] = value.strip().strip('"\'')
        break
    return entries


def dev_hdd0_dir(root: Path) -> Path:
    """The dev_hdd0 folder RPCS3 uses, honouring a vfs.yml relocation.

    vfs.yml maps ``/dev_hdd0/`` to a path that may start with
    ``$(EmulatorDir)``; that variable is the RPCS3 folder unless vfs.yml
    gives ``$(EmulatorDir)`` its own (non-empty) value.
    """
    default = root / "dev_hdd0"
    entries = _vfs_entries(root)
    configured = entries.get("/dev_hdd0/") or entries.get("/dev_hdd0")
    if not configured:
        return default
    emulator_dir = entries.get("$(EmulatorDir)") or (str(root) + "/")
    if not emulator_dir.endswith(("/", "\\")):
        emulator_dir += "/"
    resolved = configured.replace("$(EmulatorDir)", emulator_dir)
    path = Path(resolved)
    if not path.is_absolute():
        path = root / path
    return path


def find_param_sfo(root: Path) -> Path | None:
    """Locate the installed game's PARAM.SFO, if RPCS3 knows about the game."""
    candidates = [dev_hdd0_dir(root) / "game" / TITLE_ID / "PARAM.SFO"]
    if candidates[0] != root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO":
        candidates.append(root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO")
    for game_path in games_config_paths(root):
        candidates.append(game_path / "PARAM.SFO")
        candidates.append(game_path / "PS3_GAME" / "PARAM.SFO")
    return next((path for path in candidates if path.is_file()), None)


def game_version_problem(root: Path) -> str | None:
    """Describe why the installed game will not match the patch, if it will not."""
    sfo = find_param_sfo(root)
    if sfo is None:
        return ("Could not find Spartacus Legends in this RPCS3 folder. Install the "
                f"USA release ({TITLE_ID}) and let RPCS3 list it before playing.")
    try:
        fields = read_param_sfo(sfo)
    except (OSError, ValueError) as error:
        return f"Could not read {sfo}: {error}"
    title_id = fields.get("TITLE_ID", "")
    version = fields.get("APP_VER") or fields.get("VERSION", "")
    if title_id and title_id != TITLE_ID:
        return (f"The game installed here is {title_id}, not {TITLE_ID}. Only the USA "
                "release is supported.")
    if version and version not in SUPPORTED_BUILDS:
        supported = " or ".join(SUPPORTED_BUILDS)
        return (f"The installed game is version {version}. Only {supported} are "
                "supported, so the patch will not apply. Either update to "
                "01.06 or remove the game's update data (Manage > Title "
                f"Database, or delete dev_hdd0/game/{TITLE_ID}-UPDATE) and "
                "reinstall the base game.")
    return None


UNUSED_FOLDER_MESSAGE = (
    "This RPCS3 folder has probably never been used to play Spartacus "
    f"Legends: it has neither the game ({TITLE_ID}) nor an RPCN account. "
    "Choose the RPCS3 you actually play from - in that RPCS3, right-click "
    "Spartacus Legends and choose Open Install Folder, then go up until you "
    "reach the folder that contains rpcs3.exe. Nothing was installed here.")


def unused_folder_problem(root: Path) -> str | None:
    """One clear message when this RPCS3 has never run the game, else None."""
    if find_param_sfo(root) is not None:
        return None
    if (root / "config" / "rpcn.yml").is_file():
        return None
    return UNUSED_FOLDER_MESSAGE


def detected_game_version(root: Path) -> str | None:
    """PARAM.SFO APP_VER when it is a supported build, otherwise None.

    None means "unknown": callers must not guess a build from it, because the
    title version decides which saves the server serves.
    """
    sfo = find_param_sfo(root)
    if sfo is None:
        return None
    try:
        fields = read_param_sfo(sfo)
    except (OSError, ValueError):
        return None
    version = fields.get("APP_VER") or fields.get("VERSION", "")
    return version if version in SUPPORTED_BUILDS else None


def rpcn_problem(root: Path) -> str | None:
    """Describe why RPCN sign-in will fail, if it will."""
    rpcn = root / "config" / "rpcn.yml"
    if not rpcn.is_file():
        return ("No RPCN account is set up in RPCS3 yet. Create one in RPCS3 under "
                "Manage > RPCN > RPCN Account before starting the game.")
    for line in rpcn.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().strip('"\'') == "NPID" and value.strip().strip('"\''):
            return None
    return ("RPCN has no account name saved. Create or sign in to an RPCN account in "
            "RPCS3 under Manage > RPCN > RPCN Account before starting the game.")


def parse_indented_map(text: str) -> dict:
    """Parse the indentation-only YAML maps RPCS3 writes for its config files."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for line in text.splitlines():
        if line.lstrip().startswith(("#", "-")) or not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        indent = len(key) - len(key.lstrip())
        key = key.strip().strip('"\'')
        value = value.strip().strip('"\'')
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        parent = stack[-1][1]
        if value:
            parent[key] = value
        else:
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def lookup(tree: dict, *keys: str):
    """Follow a path of map keys, returning None if any level is missing."""
    node = tree
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def eboot_coverage_check(imported_text: str,
                         eboot_elf: Path | None) -> tuple[bool, str, bool]:
    """Report whether the user's executable hash has a patch section."""
    if eboot_elf is None:
        return (True, "No decrypted executable supplied; hash coverage not "
                      "checked", False)
    path = Path(eboot_elf)
    if not path.is_file():
        return (False, f"Decrypted executable not found: {path}", False)
    if not eboot_source.is_elf(path):
        return (False,
                f"{path} is not a decrypted ELF. Run RPCS3 Utilities > "
                "Decrypt PS3 Binaries and choose the produced .elf, then "
                "verify again.",
                False)
    try:
        user_hash = ppu_hash.ppu_hash_file(path)
    except (OSError, ValueError) as error:
        return (False, f"Could not hash {path}: {error}", False)
    if f"{user_hash}:" in imported_text:
        return (True,
                f"Executable hash {user_hash} is covered by the installed "
                "patches", False)
    return (False,
            f"Your executable hash {user_hash} is not covered by the "
            "installed patches. The dump differs from the supported "
            "executables, so RPCS3 applies none of the patches. Run the "
            "installer with --adaptive --eboot-elf <decrypted .elf> to locate "
            "the patch sites by signature (experimental).",
            False)


def executable_coverage_check(imported_text: str,
                              user_hash: str) -> tuple[bool, str, bool]:
    """Coverage line for a hash already computed (no second decrypt)."""
    if f"{user_hash}:" in imported_text:
        return (True, f"Executable hash {user_hash} is covered by the "
                      "installed patches", False)
    return (False,
            f"Your executable hash {user_hash} is not covered by the "
            "installed patches, so RPCS3 applies none of them. Run the "
            "installer again: it generates a matching patch for a different "
            "dump automatically (experimental).", False)


def boot_status_check(boot) -> tuple[bool, str, bool] | None:
    """Advisory line from RPCS3.log's last Spartacus boot, when there is one."""
    if boot is None:
        return None
    if boot.unreadable:
        return (True, boot.summary(), False)
    if boot.compatibility_applied:
        return (True, boot.summary(), False)
    return (False, boot.summary() + " Install or repair the setup, then "
            "cold-boot the game again.", False)


def verify_setup(rpcs3_folder: Path,
                 server_base_dir: Path | None = None, *,
                 eboot_elf: Path | None = None,
                 executable_hash: str | None = None,
                 boot_status=None,
                 ) -> list[tuple[bool, str, bool]]:
    """Re-read RPCS3's own files and report what is actually configured.

    Each check is (passed, message, required).  Required checks cover what this
    installer writes; the rest describe the surrounding setup the user owns.
    """
    root = find_rpcs3_root(rpcs3_folder)
    unused = unused_folder_problem(root)
    if unused:
        # One plain answer instead of separate "no game" / "no RPCN" lines
        # that read like two small problems with the right folder.
        return [(False, unused, True)]
    server_base_dir = (application_dir() if server_base_dir is None
                       else Path(server_base_dir))
    checks: list[tuple[bool, str, bool]] = []

    detected = detected_game_version(root)
    version = detected or GAME_VERSION
    ppu_header = SUPPORTED_BUILDS[version]

    config = server_config_path(server_base_dir)
    try:
        configured_version = read_title_version(config)
        config_error = None
    except ValueError as error:
        configured_version = None
        config_error = str(error)
    if config_error:
        config_message = config_error
    elif detected is None:
        config_message = (
            "The game version could not be detected, so the server version "
            f"in {config} was left as "
            f"{configured_version or 'not set'}. Choose the version you play "
            "when installing.")
    elif configured_version is None:
        config_message = f"Server version configuration is missing: {config}"
    elif configured_version != version:
        config_message = (f"Server is configured for game version "
                          f"{configured_version}, but RPCS3 has {version}: "
                          f"{config}")
    else:
        config_message = (f"Server configured for game version {version} "
                          f"in {config}")
    checks.append((detected is not None and configured_version == version,
                   config_message, True))

    imported = root / "patches" / "imported_patch.yml"
    text = imported.read_text(encoding="utf-8-sig") if imported.is_file() else ""
    installed = ppu_header in text and f'  "{COMPATIBILITY_PATCH}":' in text
    checks.append((installed, f"Compatibility patch installed in {imported}", True))
    try:
        if executable_hash is not None:
            checks.append(executable_coverage_check(text, executable_hash))
        else:
            checks.append(eboot_coverage_check(text, eboot_elf))
    except Exception as error:  # a diagnostic must not break verification
        checks.append((False, f"Could not inspect the executable hash: {error}",
                       False))
    boot_check = boot_status_check(boot_status)
    if boot_check is not None:
        checks.append(boot_check)

    patch_config = root / "config" / "patch_config.yml"
    config_text = (patch_config.read_text(encoding="utf-8-sig")
                   if patch_config.is_file() else "")
    enabled = lookup(parse_indented_map(config_text), ppu_header.rstrip(":"),
                     COMPATIBILITY_PATCH, "Spartacus Legends", TITLE_ID,
                     version, "Enabled")
    checks.append((str(enabled).lower() == "true",
                   "Compatibility patch enabled for "
                   f"{TITLE_ID} {version} in {patch_config}", True))

    custom_config = root / "config" / "custom_configs" / f"config_{TITLE_ID}.yml"
    net = lookup(parse_indented_map(
        custom_config.read_text(encoding="utf-8-sig")
        if custom_config.is_file() else ""), "Net") or {}
    for key, expected in (("IP swap list", IP_SWAP),
                          ("Internet enabled", "Connected"),
                          ("PSN status", "RPCN")):
        checks.append((net.get(key) == expected,
                       f"Network setting {key}: {expected}", True))

    game_problem = game_version_problem(root)
    checks.append((game_problem is None,
                   game_problem or f"Game installed: {TITLE_ID} version {version}",
                   False))
    rpcn = rpcn_problem(root)
    checks.append((rpcn is None, rpcn or "RPCN account configured", False))
    raw_bind_address = net.get("Bind address", "")
    # parse_indented_map represents an explicitly empty YAML scalar ('' or
    # blank) as an empty mapping. Only a real scalar address is actionable.
    bind_address = (raw_bind_address.strip()
                    if isinstance(raw_bind_address, str) else "")
    if bind_address and bind_address not in {"0.0.0.0", "127.0.0.1"}:
        checks.append((
            False,
            f"RPCS3 Bind address is {bind_address}. The default loopback "
            "server cannot be reached from a bound game socket. Either clear "
            "Bind address for a normal single-client setup, or start "
            "SpartacusLegendsServer.exe with --host 0.0.0.0 "
            "--advertise-host <server-LAN-IP>. The advertised host is the "
            "server address RPCS3 can reach, not RPCS3's Bind address.",
            False,
        ))
    return checks


def report_verification(checks: list[tuple[bool, str, bool]]) -> tuple[bool, bool]:
    """Print each check; return (all required passed, all advisory passed)."""
    for passed, message, required in checks:
        marker = "OK" if passed else ("XX" if required else "!!")
        print(f"  [{marker}] {message}")
    return (all(passed for passed, _, required in checks if required),
            all(passed for passed, _, required in checks if not required))


def rpcs3_is_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq rpcs3.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return "rpcs3.exe" in result.stdout.lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rpcs3_folder", nargs="?", help="RPCS3 folder (or its patches folder)")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--verify", action="store_true",
                        help="report what is currently configured and exit")
    parser.add_argument("--no-wait", action="store_true",
                        help="do not pause before closing the window")
    parser.add_argument("--eboot", type=Path, metavar="PATH",
                        help="EBOOT.BIN to check instead of the one found in "
                             "the RPCS3 folder. It is copied to a temporary "
                             "folder and decrypted with rpcs3.exe --decrypt "
                             "(the user's own RPCS3 licence).")
    parser.add_argument("--eboot-elf", type=Path, metavar="PATH",
                        help="already decrypted EBOOT .elf (RPCS3 Utilities > "
                             "Decrypt PS3 Binaries), for when automatic "
                             "decryption does not work.")
    parser.add_argument("--adaptive", action="store_true",
                        help="EXPERIMENTAL: always generate a patch section "
                             "for this executable's PPU hash. This already "
                             "happens automatically for a dump whose hash is "
                             "not one of the supported ones.")
    parser.add_argument("--no-adaptive", action="store_true",
                        help="never generate a patch section for a different "
                             "dump; only install the shipped patch.")
    parser.add_argument("--no-hash-check", action="store_true",
                        help="do not decrypt and hash the game's executable.")
    parser.add_argument("--allow-unused-folder", action="store_true",
                        help="install even though this RPCS3 folder has "
                             "neither the game nor an RPCN account.")
    parser.add_argument("--title-version", choices=sorted(SUPPORTED_BUILDS),
                        help="game version to configure the server for when "
                             "it cannot be detected from the game.")
    return parser.parse_args()


def maybe_pause(no_wait: bool) -> None:
    if not no_wait and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nPress Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass


def run(args: argparse.Namespace) -> int:
    folder = args.rpcs3_folder or input("Paste or drag in your RPCS3 folder, then press Enter: ").strip(' "')
    if not folder:
        print("No folder supplied.", file=sys.stderr)
        return 2
    try:
        root = find_rpcs3_root(Path(folder))
    except OSError as error:
        print(f"INSTALL ERROR: {error}", file=sys.stderr)
        return 1

    if args.eboot is not None and args.eboot_elf is not None:
        print("INSTALL ERROR: use either --eboot (encrypted) or --eboot-elf "
              "(decrypted), not both.", file=sys.stderr)
        return 2
    if args.adaptive and getattr(args, "no_adaptive", False):
        print("INSTALL ERROR: --adaptive and --no-adaptive contradict each "
              "other.", file=sys.stderr)
        return 2

    try:
        import game_detect
    except ImportError:  # Imported as tools.patch_installer by the unit tests.
        from tools import game_detect
    # Read RPCS3's log before anything runs rpcs3.exe. Decrypting restores
    # the log anyway; the order keeps the last game boot as the evidence.
    boot = game_detect.last_boot_status(root)
    try:
        game = game_detect.detect_game(root)
    except (OSError, game_detect.DetectionError) as error:
        print(f"WARNING: {error}\n")
        game = None
    if game is not None:
        print(f"Found {game.describe()} in {game.game_dir}")
    source = args.eboot_elf or args.eboot
    if source is None and game is not None:
        source = game.eboot_path
    if args.adaptive and source is None:
        print("INSTALL ERROR: --adaptive needs the game's executable. No "
              "EBOOT.BIN was found in this RPCS3 folder; pass --eboot or "
              "--eboot-elf.", file=sys.stderr)
        return 2

    check = None
    if (source is not None and game is not None
            and not getattr(args, "no_hash_check", False)):
        print("Checking the game's executable (decrypting a temporary copy "
              "with this RPCS3)...")
        try:
            check = game_detect.check_executable(game, source=source,
                                                 boot=boot)
        except (OSError, ValueError, eboot_source.EbootSourceError,
                game_detect.DetectionError) as error:
            print(f"WARNING: could not check the executable: {error}\n"
                  "Use RPCS3 Utilities > Decrypt PS3 Binaries and pass the "
                  ".elf with --eboot-elf to check it.\n")
        else:
            print(f"Executable: {check.summary()}\n")
    user_hash = check.ppu_hash if check is not None else None

    if args.verify:
        print(f"Checking the Spartacus Legends setup in {root}\n")
        installed, surroundings = report_verification(
            verify_setup(root, eboot_elf=args.eboot_elf,
                         executable_hash=user_hash, boot_status=boot))
        if not installed:
            print("\nThe items marked [XX] are missing. Run this installer without "
                  "--verify to write them.", file=sys.stderr)
        elif not surroundings:
            print("\nRPCS3 is configured, but the items marked [!!] will still stop the "
                  "game from reaching the main menu.", file=sys.stderr)
        else:
            print("\nSETUP OK.")
        return 0 if installed and surroundings else 1

    low = low_integrity_problem()
    if low:
        print(f"INSTALL ERROR: {low}", file=sys.stderr)
        return 1

    if rpcs3_is_running():
        print("INSTALL ERROR: Close RPCS3 before running the installer. RPCS3 rewrites "
              "its configuration when it closes, which would undo this setup.",
              file=sys.stderr)
        return 1

    unused = unused_folder_problem(root)
    allow_unused = bool(getattr(args, "allow_unused_folder", False))
    if unused:
        print(f"WRONG RPCS3 FOLDER? {unused}\n", file=sys.stderr)
        if not allow_unused:
            if args.yes:
                print("No changes made. Run the installer on the RPCS3 you "
                      "play from, or add --allow-unused-folder to install "
                      "here anyway.", file=sys.stderr)
                return 1
            if input("Install into this folder anyway? [y/N]: ").strip() \
                    .lower() not in {"y", "yes"}:
                print("No changes made.")
                return 1
            allow_unused = True
    else:
        for problem in (game_version_problem(root), rpcn_problem(root)):
            if problem:
                print(f"WARNING: {problem}\n")

    title_version = getattr(args, "title_version", None)
    if title_version is None and detected_game_version(root) is None:
        current = None
        try:
            current = read_title_version(server_config_path(application_dir()))
        except ValueError:
            pass
        print("The game version could not be detected, so the server's "
              "version setting is left unchanged "
              f"({current or 'not set'}). Pass --title-version 01.00 or "
              "--title-version 01.06 to set it.\n")

    adaptive = args.adaptive
    unpatchable = None
    if check is not None and check.status == game_detect.STATUS_UNKNOWN:
        if getattr(args, "no_adaptive", False):
            unpatchable = ("it is a different dump and --no-adaptive was "
                           "given")
        elif check.can_generate:
            adaptive = True
            print("This is a different dump of the game. A patch matching "
                  "its executable will be generated (EXPERIMENTAL).\n")
        else:
            unpatchable = check.problem
    elif (check is not None and check.status == game_detect.STATUS_GENERATED
          and not getattr(args, "no_adaptive", False)):
        adaptive = True  # keep the generated section current

    print("Will install the patch and configure Spartacus Legends in RPCS3.")
    print("Existing configuration files are backed up and unrelated settings are retained.")
    print(f"The game's PPU cache will be removed from: {root / 'cache' / TITLE_ID}")
    if not args.yes and input("Continue? [y/N]: ").strip().lower() not in {"y", "yes"}:
        print("No changes made.")
        return 0
    try:
        result = install_setup(
            root, eboot=source if adaptive else None, adaptive=adaptive,
            allow_decrypt=True, allow_unused_folder=allow_unused,
            title_version=title_version)
    except (OSError, ValueError, adaptive_patch.PatchResolutionError,
            eboot_source.EbootSourceError) as error:
        print(f"INSTALL ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Installed Spartacus Legends patches in {result.imported_patch}")
    print(f"Configured the game in {result.custom_config}")
    if result.server_config_written:
        print(f"Configured the server for game version "
              f"{result.title_version} in {result.server_config}")
    else:
        print(f"Left the server's version setting unchanged in "
              f"{result.server_config}")
    print("Enabled the compatibility patch.")
    if adaptive:
        if result.adaptive_report is not None:
            print(f"ADAPTIVE (EXPERIMENTAL): located the patch sites for "
                  f"executable hash {result.adaptive_hash} and installed a "
                  "generated patch section.")
            print(f"Signature report: {result.adaptive_report}")
        else:
            print(f"Adaptive mode: executable hash {result.adaptive_hash} is "
                  "already covered by the distributed patch; nothing extra "
                  "was needed.")
    print("Cleared the game's PPU cache." if result.cache_cleared
          else "The game's PPU cache was already clear.")
    for backup in result.backups:
        print(f"Backup created: {backup}")

    print("\nChecking the result:")
    installed, surroundings = report_verification(
        verify_setup(root, eboot_elf=args.eboot_elf,
                     executable_hash=user_hash))
    if unpatchable:
        print("\nSETUP INCOMPLETE: the game's executable is a different dump "
              f"that cannot be patched automatically: {unpatchable}",
              file=sys.stderr)
        return 1
    if not installed:
        print("\nSETUP INCOMPLETE: fix the items marked [XX] above, then run this "
              "installer again.", file=sys.stderr)
        return 1
    if not surroundings:
        print("\nRPCS3 is configured, but the items marked [!!] will still stop the game "
              "from reaching the main menu. Fix those, then start "
              "SpartacusLegendsServer.exe.", file=sys.stderr)
        return 1
    print("\nSETUP OK. Start SpartacusLegendsServer.exe, then cold-boot the game in RPCS3.")
    return 0


def main() -> int:
    # Keep the report readable when a user pipes this window into a log file:
    # unbuffered stderr would otherwise overtake the buffered check list.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    try:
        code = run(args)
    except KeyboardInterrupt:
        print("\nCancelled. No further changes made.")
        code = 1
    maybe_pause(args.no_wait)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
