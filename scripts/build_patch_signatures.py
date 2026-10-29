#!/usr/bin/env python3
"""Generate tools/patch_signatures.json from the reference ELFs and patch YAML.

The distributed patch YAML stays read-only and byte-identical. This script
reads its required "Server emulator compatibility" entries, measures a masked
instruction window around each site in the known-good decrypted executable,
grows the window until it is unique, and records the original/replacement words
plus a target signature for branch replacements.

Run from the repository root:

    python scripts\\build_patch_signatures.py

It writes tools/patch_signatures.json and prints one line per generated site.
The Qt-free resolver (tools/adaptive_patch.py) consumes that JSON at install
time; no addresses are ever copied from the reference build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import adaptive_patch as ap
import ppu_hash

DEFAULT_YAML = ROOT / "packaging" / "SpartacusLegends_ServerPatch.yml"
DEFAULT_OUTPUT = TOOLS / "patch_signatures.json"
COMPATIBILITY_PATCH = "Spartacus Legends - Server emulator compatibility"
DEFAULT_ELVES = {
    "01.00": ROOT / "decrypted" / "EBOOT.elf",
    "01.06": ROOT / "decrypted" / "EBOOT-1.06.elf",
}

PPU_HEADER_RE = re.compile(r"^(PPU-[0-9a-f]{40}):\s*$")
PATCH_NAME_RE = re.compile(r'^  "(.*)":\s*$')
ENTRY_RE = re.compile(
    r"^-\s*\[\s*be32\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*\]"
    r"\s*(?:#\s*(.*))?$")


class GenerationError(RuntimeError):
    pass


def parse_required_patches(text: str) -> dict[str, dict]:
    """Parse the required compatibility patch from each PPU section."""
    patches: dict[str, dict] = {}
    current: dict | None = None
    mode = ""
    for raw in text.splitlines():
        header = PPU_HEADER_RE.match(raw.strip())
        if header and not raw.startswith((" ", "\t")):
            current = None
            current_header = header.group(1)
            continue
        name = PATCH_NAME_RE.match(raw)
        if name is not None:
            if name.group(1) == COMPATIBILITY_PATCH:
                current = {
                    "ppu_header": current_header,
                    "games": [],
                    "author": "",
                    "notes": [],
                    "patch_version": "",
                    "entries": [],
                }
                patches[current_header] = current
                mode = ""
            else:
                current = None
            continue
        if current is None:
            continue
        stripped = raw.strip()
        if raw.startswith("    Games:"):
            mode = "games"
        elif raw.startswith("    Author:"):
            mode = ""
            current["author"] = stripped.split(":", 1)[1].strip().strip('"')
        elif raw.startswith("    Notes:"):
            mode = "notes"
        elif raw.startswith("    Patch Version:"):
            mode = ""
            current["patch_version"] = (
                stripped.split(":", 1)[1].strip().strip('"'))
        elif raw.startswith("    Patch:"):
            mode = "entries"
        elif mode == "notes" and raw.startswith("      "):
            current["notes"].append(stripped)
        elif mode == "games" and stripped.startswith('"'):
            game = stripped[1:stripped.rfind('"')]
            current["games"].append([game, []])
            mode = "game_versions"
        elif mode == "game_versions" and "NPUB30746:" in stripped:
            inside = stripped.split("[", 1)[1].split("]", 1)[0]
            current["games"][-1][1] = [
                value for value in re.split(r"[,\s]+", inside) if value
            ]
        elif mode == "entries" and stripped.startswith("- ["):
            entry = ENTRY_RE.match(stripped)
            if entry is None:
                raise GenerationError(f"cannot parse patch entry: {stripped}")
            current["entries"].append({
                "address": int(entry.group(1), 0),
                "replacement": int(entry.group(2), 0),
                "label": (entry.group(3) or "").strip()
                         or f"patch entry {len(current['entries']) + 1}",
            })
    return patches


def _branch_target(address: int, word: int) -> int:
    return ap._branch_destination(word, address)


def _candidate_shapes():
    """Window shapes to try, shortest first, mostly looking backwards.

    Code after a patched branch can differ between builds (the 01.06 reference
    proves it), so a backward-heavy window is preferred. The plan's 16-32
    instruction range is respected; every shape must be unique in the
    reference, and growing the window resolves ambiguity.
    """
    shapes = []
    for total in range(16, 33):
        for before in range(total - 1, 7, -1):
            after = total - 1 - before
            if 1 <= after <= 8:
                shapes.append((before, after))
    return shapes


def _window_for(elf: ap.ElfImage, address: int, label: str, kind: str,
                cross_elves: tuple[ap.ElfImage, ...] = ()) -> ap.WindowSignature:
    fallback = None
    for before, after in _candidate_shapes():
        try:
            signature = ap.build_window_around(elf, address, before, after)
        except ValueError:
            continue
        if len(ap.locate(elf, signature)) != 1:
            continue
        cross_counts = [len(ap.locate(cross, signature))
                        for cross in cross_elves]
        # A window that is ambiguous in another supported reference build is
        # not acceptable evidence; zero matches there is fine when that build's
        # code genuinely changed at this site.
        if any(count > 1 for count in cross_counts):
            continue
        if cross_elves and all(count == 1 for count in cross_counts):
            # Best evidence: unique in the reference AND in the other supported
            # build whose surrounding code is known to differ. This is what
            # lets a signature survive a relocated dump instead of relying on
            # bytes that only happen to be adjacent in one build.
            return signature
        if fallback is None:
            fallback = signature
    if fallback is not None:
        return fallback
    raise GenerationError(
        f"{label}: {kind} window at 0x{address:08X} has no unique masked "
        "signature in the reference executable")


def build_patch_set(title_version: str, elf_bytes: bytes, patch: dict,
                    cross_elves: tuple[ap.ElfImage, ...] = ()
                    ) -> tuple[ap.PatchSetSignature, dict]:
    elf = ap.ElfImage(elf_bytes)
    sites = []
    for entry in patch["entries"]:
        address = entry["address"]
        word = elf.load_word(address)
        if word is None:
            raise GenerationError(
                f"{entry['label']}: 0x{address:08X} is outside the reference "
                "executable")
        replacement = entry["replacement"]
        window = _window_for(elf, address, entry["label"], "site",
                             cross_elves)
        target_signature = None
        if (word >> 26) in (ap.PRIMARY_B, ap.PRIMARY_BC):
            # The shipped patches replace conditional branches with either an
            # unconditional branch (recompute the displacement) or a nop
            # (verify the target still matches). Both need the target's own
            # signature so relocation cannot point a patch at the wrong code.
            target_address = _branch_target(address, word)
            target_signature = _window_for(
                elf, target_address, entry["label"], "branch target",
                cross_elves)
        sites.append(ap.PatchSiteSignature(
            label=entry["label"],
            address=address,
            original=word,
            replacement=replacement,
            window=window,
            target=target_signature,
        ))
    notes = " ".join(patch["notes"]).strip()
    patch_set = ap.PatchSetSignature(
        name=COMPATIBILITY_PATCH,
        title_version=title_version,
        games=tuple((name, tuple(versions))
                    for name, versions in patch["games"]),
        author=patch["author"] or "Spartacus Legends preservation project",
        notes=notes,
        patch_version=patch["patch_version"] or "4.2",
        sites=tuple(sites),
    )
    reference = {
        "sha256": hashlib.sha256(elf_bytes).hexdigest(),
        "ppu_hash": ppu_hash.ppu_hash(elf_bytes),
    }
    return patch_set, reference


def generate(yaml_path: Path, elves: dict[str, Path]) -> dict:
    patches = parse_required_patches(yaml_path.read_text(encoding="utf-8"))
    # Parse the game version of each required patch before building any one of
    # them, so each build can use the other supported reference as a second
    # uniqueness check.
    resolved: dict[str, tuple[str, dict, Path]] = {}
    for ppu_header, patch in patches.items():
        versions = patch["games"][0][1] if patch["games"] else []
        if not versions:
            raise GenerationError("patch has no game version entry")
        version = versions[0]
        elf_path = elves.get(version)
        if elf_path is None or not Path(elf_path).is_file():
            raise GenerationError(
                f"reference ELF for {version} is missing: {elf_path}")
        resolved[version] = (version, patch, Path(elf_path))
    elf_images = {
        version: ap.ElfImage(elf_path.read_bytes())
        for version, (_v, _patch, elf_path) in resolved.items()
    }
    builds: dict[str, ap.PatchSetSignature] = {}
    generated_from: dict[str, dict] = {}
    for version, (_version, patch, elf_path) in resolved.items():
        cross_elves = tuple(
            image for other, image in elf_images.items() if other != version)
        patch_set, reference = build_patch_set(
            version, elf_path.read_bytes(), patch, cross_elves)
        builds[version] = patch_set
        generated_from[version] = {
            "elf": elf_path.name,
            **reference,
        }
    return {
        "schema": 1,
        "required_patch": COMPATIBILITY_PATCH,
        "generated_from": generated_from,
        "builds": {
            version: ap.patch_set_to_dict(patch_set)
            for version, patch_set in builds.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", type=Path, default=DEFAULT_YAML)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--elf", action="append", default=[], metavar="VERSION=PATH",
        help="reference decrypted ELF override, e.g. 01.00=decrypted/EBOOT.elf")
    args = parser.parse_args(argv)
    elves = dict(DEFAULT_ELVES)
    for value in args.elf:
        version, separator, path = value.partition("=")
        if not separator:
            parser.error(f"--elf needs VERSION=PATH, got {value!r}")
        elves[version] = Path(path)
    try:
        document = generate(args.yaml, elves)
    except (GenerationError, ValueError, OSError) as error:
        print(f"SIGNATURE GENERATION FAILED: {error}", file=sys.stderr)
        return 1
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    for version, patch_set in sorted(document["builds"].items()):
        for site in patch_set["sites"]:
            target = site["target"]
            target_text = (
                f" target={target['site_index']}.." if target else "")
            print(
                f"{version} 0x{site['address']:08X} "
                f"0x{site['original']:08X}->0x{site['replacement']:08X} "
                f"window={len(site['window']['instructions'])}"
                f"{target_text}  {site['label']}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
