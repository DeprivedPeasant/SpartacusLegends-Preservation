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
GAME_VERSION = "01.00"
IPC_PORT = "28012"
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
        "IP swap list": IP_SWAP,
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
        "IPC Port": IPC_PORT,
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


def find_param_sfo(root: Path) -> Path | None:
    """Locate the installed game's PARAM.SFO, if RPCS3 knows about the game."""
    candidates = [root / "dev_hdd0" / "game" / TITLE_ID / "PARAM.SFO"]
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
    if version and version != GAME_VERSION:
        return (f"The installed game is version {version}, not {GAME_VERSION}. The patch "
                "only matches version 01.00, so it will not apply. Remove the game's "
                "update data (Manage > Title Database, or delete "
                f"dev_hdd0/game/{TITLE_ID}-UPDATE) and reinstall the base game.")
    return None


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


def verify_setup(rpcs3_folder: Path) -> list[tuple[bool, str, bool]]:
    """Re-read RPCS3's own files and report what is actually configured.

    Each check is (passed, message, required).  Required checks cover what this
    installer writes; the rest describe the surrounding setup the user owns.
    """
    root = find_rpcs3_root(rpcs3_folder)
    checks: list[tuple[bool, str, bool]] = []

    imported = root / "patches" / "imported_patch.yml"
    text = imported.read_text(encoding="utf-8-sig") if imported.is_file() else ""
    installed = PPU_HEADER in text and f'  "{COMPATIBILITY_PATCH}":' in text
    checks.append((installed, f"Compatibility patch installed in {imported}", True))

    patch_config = root / "config" / "patch_config.yml"
    config_text = (patch_config.read_text(encoding="utf-8-sig")
                   if patch_config.is_file() else "")
    enabled = lookup(parse_indented_map(config_text), PPU_HEADER.rstrip(":"),
                     COMPATIBILITY_PATCH, "Spartacus Legends", TITLE_ID,
                     GAME_VERSION, "Enabled")
    checks.append((str(enabled).lower() == "true",
                   "Compatibility patch enabled for "
                   f"{TITLE_ID} {GAME_VERSION} in {patch_config}", True))

    custom_config = root / "config" / "custom_configs" / f"config_{TITLE_ID}.yml"
    net = lookup(parse_indented_map(
        custom_config.read_text(encoding="utf-8-sig")
        if custom_config.is_file() else ""), "Net") or {}
    for key, expected in (("IP swap list", IP_SWAP),
                          ("Internet enabled", "Connected"),
                          ("PSN status", "RPCN")):
        checks.append((net.get(key) == expected,
                       f"Network setting {key}: {expected}", True))

    ipc_config = root / "config" / "ipc.yml"
    ipc = parse_indented_map(ipc_config.read_text(encoding="utf-8-sig")
                             if ipc_config.is_file() else "")
    checks.append((str(ipc.get("IPC Server enabled", "")).lower() == "true"
                   and str(ipc.get("IPC Port", "")) == IPC_PORT,
                   f"RPCS3 IPC server enabled on port {IPC_PORT}", True))

    game_problem = game_version_problem(root)
    checks.append((game_problem is None,
                   game_problem or f"Game installed: {TITLE_ID} version {GAME_VERSION}",
                   False))
    rpcn = rpcn_problem(root)
    checks.append((rpcn is None, rpcn or "RPCN account configured", False))
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

    if args.verify:
        print(f"Checking the Spartacus Legends setup in {root}\n")
        installed, surroundings = report_verification(verify_setup(root))
        if not installed:
            print("\nThe items marked [XX] are missing. Run this installer without "
                  "--verify to write them.", file=sys.stderr)
        elif not surroundings:
            print("\nRPCS3 is configured, but the items marked [!!] will still stop the "
                  "game from reaching the main menu.", file=sys.stderr)
        else:
            print("\nSETUP OK.")
        return 0 if installed and surroundings else 1

    if rpcs3_is_running():
        print("INSTALL ERROR: Close RPCS3 before running the installer. RPCS3 rewrites "
              "its configuration when it closes, which would undo this setup.",
              file=sys.stderr)
        return 1

    for problem in (game_version_problem(root), rpcn_problem(root)):
        if problem:
            print(f"WARNING: {problem}\n")

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
    print(f"Enabled the compatibility patch and RPCS3 IPC server on port {IPC_PORT}.")
    print("Cleared the game's PPU cache." if result.cache_cleared
          else "The game's PPU cache was already clear.")
    for backup in result.backups:
        print(f"Backup created: {backup}")

    print("\nChecking the result:")
    installed, surroundings = report_verification(verify_setup(root))
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
