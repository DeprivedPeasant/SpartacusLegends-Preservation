#!/usr/bin/env python3
"""Configure RPCS3 for the Spartacus Legends preservation server."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys


PPU_HEADER = "PPU-81471d050c14f4d20b4027686f8b571dafd32394:"
TITLE_ID = "NPUB30746"
COMPATIBILITY_PATCH = "Spartacus Legends - Server emulator compatibility"
PROJECT_PATCHES = (
    f'  "{COMPATIBILITY_PATCH}":',
    '  "Spartacus Legends - One-hit fight debug cheat (optional)":',
    '  "Spartacus Legends - Skip startup logo screens (optional)":',
)


@dataclass(frozen=True)
class InstallResult:
    imported_patch: Path
    custom_config: Path
    patch_config: Path
    ipc_config: Path
    backups: tuple[Path, ...]
    cache_cleared: bool


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def supplied_patch_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "SpartacusLegends_ServerPatch.yml"
    return application_dir() / "packaging" / "SpartacusLegends_ServerPatch.yml"


def ppu_block_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if lines[index] and not lines[index].startswith((" ", "\t")):
            return index
    return len(lines)


def remove_project_patches(lines: list[str]) -> tuple[list[str], bool]:
    """Remove just this project's named entries from its PPU section."""
    try:
        section_start = lines.index(PPU_HEADER)
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


def supplied_entries(template: str) -> list[str]:
    lines = template.splitlines()
    start = lines.index(PPU_HEADER) + 1
    return lines[start:ppu_block_end(lines, start - 1)]


def merge_patch(existing: str, template: str) -> str:
    """Merge project entries while retaining every other imported RPCS3 patch."""
    existing_lines = existing.splitlines()
    if existing_lines and existing_lines[0].startswith("\ufeff"):
        existing_lines[0] = existing_lines[0].lstrip("\ufeff")
    if not existing_lines:
        existing_lines = ["Version: 1.2", ""]
    if not existing_lines[0].startswith("Version:"):
        raise ValueError("imported_patch.yml does not begin with a Version header")

    remaining, found = remove_project_patches(existing_lines)
    entries = supplied_entries(template)
    if found:
        insert_at = remaining.index(PPU_HEADER) + 1
        while insert_at < len(remaining) and not remaining[insert_at].startswith('  "'):
            insert_at += 1
        merged = remaining[:insert_at] + [""] + entries + remaining[insert_at:]
    else:
        merged = remaining + ([""] if remaining[-1:] != [""] else []) + [PPU_HEADER, ""] + entries
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


def merge_top_level_settings(existing: str, settings: dict[str, str]) -> str:
    """Set scalar keys in a small top-level RPCS3 YAML document."""
    lines = existing.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    found: set[str] = set()
    for index, line in enumerate(lines):
        if line.startswith((" ", "\t")):
            continue
        for key, value in settings.items():
            if line.startswith(f"{key}:"):
                lines[index] = f"{key}: {value}"
                found.add(key)
                break
    lines.extend(f"{key}: {value}" for key, value in settings.items()
                 if key not in found)
    return "\n".join(lines).rstrip() + "\n"


def merge_patch_config(existing: str) -> str:
    """Enable only the required compatibility patch for the supported build."""
    lines = existing.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    try:
        section_start = lines.index(PPU_HEADER)
        section_end = ppu_block_end(lines, section_start)
    except ValueError:
        if lines and lines[-1]:
            lines.append("")
        section_start = len(lines)
        lines.append(PPU_HEADER)
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
            del lines[index:remove_end]
            section_end -= remove_end - index
            continue
        index += 1

    block = [
        f"  {COMPATIBILITY_PATCH}:",
        "    Spartacus Legends:",
        f"      {TITLE_ID}:",
        "        01.00:",
        "          Enabled: true",
    ]
    lines[section_start + 1:section_start + 1] = block
    return "\n".join(lines).rstrip() + "\n"


def backup_and_write(path: Path, contents: str, stamp: str,
                     backups: list[Path]) -> None:
    current = path.read_text(encoding="utf-8-sig") if path.exists() else None
    if current == contents:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        suffix = 1
        while backup.exists():
            backup = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
            suffix += 1
        shutil.copy2(path, backup)
        backups.append(backup)
    path.write_text(contents, encoding="utf-8", newline="\n")


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


def install_setup(rpcs3_folder: Path) -> InstallResult:
    root = find_rpcs3_root(rpcs3_folder)
    template_path = supplied_patch_path()
    if not template_path.is_file():
        raise FileNotFoundError(f"Supplied patch file is missing: {template_path}")

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
        "IP swap list": "onlineconfigservice.ubi.com=127.0.0.1",
        "Internet enabled": "Connected",
        "PSN status": "RPCN",
    })

    patch_config = root / "config" / "patch_config.yml"
    patch_existing = (patch_config.read_text(encoding="utf-8-sig")
                      if patch_config.exists() else "")
    patch_contents = merge_patch_config(patch_existing)

    ipc_config = root / "config" / "ipc.yml"
    ipc_existing = (ipc_config.read_text(encoding="utf-8-sig")
                    if ipc_config.exists() else "")
    ipc_contents = merge_top_level_settings(ipc_existing, {
        "IPC Server enabled": "true",
        "IPC Port": "28012",
    })

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    backup_and_write(imported_patch, imported_contents, stamp, backups)
    backup_and_write(custom_config, custom_contents, stamp, backups)
    backup_and_write(patch_config, patch_contents, stamp, backups)
    backup_and_write(ipc_config, ipc_contents, stamp, backups)

    cache = root / "cache" / TITLE_ID
    cache_cleared = cache.exists()
    if cache_cleared:
        shutil.rmtree(cache)

    return InstallResult(imported_patch, custom_config, patch_config,
                         ipc_config, tuple(backups), cache_cleared)


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    folder = args.rpcs3_folder or input("Paste or drag in your RPCS3 folder, then press Enter: ").strip(' "')
    if not folder:
        print("No folder supplied.", file=sys.stderr)
        return 2
    if rpcs3_is_running():
        print("INSTALL ERROR: Close RPCS3 before running the installer.", file=sys.stderr)
        return 1
    try:
        root = find_rpcs3_root(Path(folder))
    except OSError as error:
        print(f"INSTALL ERROR: {error}", file=sys.stderr)
        return 1
    print("Will install the patch and configure Spartacus Legends in RPCS3.")
    print("Existing configuration files are backed up and unrelated settings are retained.")
    print(f"The game's PPU cache will be removed from: {root / 'cache' / TITLE_ID}")
    if not args.yes and input("Continue? [y/N]: ").strip().lower() not in {"y", "yes"}:
        print("No changes made.")
        return 0
    try:
        result = install_setup(root)
    except (OSError, ValueError) as error:
        print(f"INSTALL ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Installed Spartacus Legends patches in {result.imported_patch}")
    print(f"Configured the game in {result.custom_config}")
    print("Enabled the compatibility patch and RPCS3 IPC server on port 28012.")
    print("Cleared the game's PPU cache." if result.cache_cleared
          else "The game's PPU cache was already clear.")
    for backup in result.backups:
        print(f"Backup created: {backup}")
    print("Setup complete. Start RPCS3 and cold-boot Spartacus Legends.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
