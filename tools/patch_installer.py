#!/usr/bin/env python3
"""Safely install the Spartacus Legends patch into RPCS3's imported_patch.yml."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys


PPU_HEADER = "PPU-81471d050c14f4d20b4027686f8b571dafd32394:"
PROJECT_PATCHES = (
    '  "Spartacus Legends - Server emulator compatibility":',
    '  "Spartacus Legends - One-hit fight debug cheat (optional)":',
    '  "Spartacus Legends - Skip startup logo screens (optional)":',
)


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
    target = find_target(Path(folder))
    print(f"Will update: {target}")
    print("Unrelated custom patches will be retained; an existing file is backed up.")
    if not args.yes and input("Continue? [y/N]: ").strip().lower() not in {"y", "yes"}:
        print("No changes made.")
        return 0
    try:
        target, backup = install_patch(Path(folder))
    except (OSError, ValueError) as error:
        print(f"INSTALL ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Installed Spartacus Legends patches in {target}")
    if backup:
        print(f"Backup created: {backup}")
    print("Restart RPCS3, enable the compatibility patch, clear the game's PPU cache, then cold-boot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
