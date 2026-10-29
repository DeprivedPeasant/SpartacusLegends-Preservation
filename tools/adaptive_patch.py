#!/usr/bin/env python3
"""Locate the shipped patch sites in a variant EBOOT by instruction signature.

RPCS3 selects patches by PPU hash, so a dump whose executable bytes differ
receives no patches at all. This module locates the same patch sites in a
user's decrypted ELF using masked instruction windows generated from the
known-good reference executable, then renders a patch section under the user's
own hash. It is deliberately all-or-nothing: if any site cannot be located
exactly once, nothing is applied.

PowerPC instruction masking follows the plan: branch link fields change when
code relocates, as do TOC/absolute-address immediates. Opcodes and registers
stay exact. The reference signature database lives in patch_signatures.json.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import struct
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
ELF_CLASS_64 = 2
ELF_DATA_BIG_ENDIAN = 2
PT_LOAD = 1
PF_X = 1
ELF_PHDR_SIZE = 56

# How many instructions are hashed around a site. The generator starts at 16
# and grows until the masked window is unique in the reference executable.
WINDOW_SIZES = (16, 20, 24, 28, 32)

PRIMARY_B = 18
PRIMARY_BC = 16
PRIMARY_ADDIS = 15
PRIMARY_ADDI = 14
PRIMARY_ORI = 24
PRIMARY_LOAD_STORE_D = frozenset((32, 34, 36, 38, 40, 44))
PRIMARY_LOAD_STORE_DS = frozenset((58, 62))

REGISTER_TOC = 2
MASK_ALL = 0xFFFFFFFF
MASK_BRANCH_LI = 0x03FFFFFC       # bits 2..25
MASK_BD = 0x0000FFFC              # bc BD bits 2..15
MASK_DS = 0x0000FFFC              # DS-form displacement bits 2..15


# ------------------------------------------------------------------ ELF image

@dataclass(frozen=True)
class Segment:
    vaddr: int
    memsz: int
    offset: int
    filesz: int
    flags: int

    @property
    def executable(self) -> bool:
        return bool(self.flags & PF_X)


class ElfImage:
    """Minimal big-endian ELF64 reader for signature matching."""

    def __init__(self, elf_bytes: bytes):
        self.data = elf_bytes
        if len(elf_bytes) < 64 or elf_bytes[:4] != ELF_MAGIC:
            raise ValueError("not an ELF file")
        if elf_bytes[4] != ELF_CLASS_64:
            raise ValueError("not a 64-bit ELF")
        if elf_bytes[5] != ELF_DATA_BIG_ENDIAN:
            raise ValueError("not a big-endian ELF")
        phoff = struct.unpack_from(">Q", elf_bytes, 0x20)[0]
        phentsize = struct.unpack_from(">H", elf_bytes, 0x36)[0]
        phnum = struct.unpack_from(">H", elf_bytes, 0x38)[0]
        if phentsize != ELF_PHDR_SIZE or phoff + phnum * phentsize > len(elf_bytes):
            raise ValueError("unsupported ELF program header table")
        segments = []
        for index in range(phnum):
            offset = phoff + index * phentsize
            (p_type, p_flags, p_offset, p_vaddr, _paddr,
             p_filesz, p_memsz, _align) = struct.unpack_from(
                ">IIQQQQQQ", elf_bytes, offset)
            if p_type != PT_LOAD:
                continue
            if p_offset + p_filesz > len(elf_bytes):
                raise ValueError("PT_LOAD segment extends past end of file")
            segments.append(Segment(p_vaddr, p_memsz, p_offset,
                                    p_filesz, p_flags))
        if not segments:
            raise ValueError("ELF has no loadable segments")
        self.segments = tuple(segments)

    def load_word(self, address: int) -> int | None:
        for segment in self.segments:
            if segment.vaddr <= address < segment.vaddr + segment.filesz:
                offset = segment.offset + (address - segment.vaddr)
                if offset + 4 > len(self.data):
                    return None
                return struct.unpack_from(">I", self.data, offset)[0]
        return None

    def executable_segments(self) -> tuple[Segment, ...]:
        return tuple(segment for segment in self.segments if segment.executable)

    def executable_addresses(self):
        """Yield every 4-byte-aligned address in an executable segment."""
        for segment in self.executable_segments():
            for address in range(segment.vaddr,
                                 segment.vaddr + segment.filesz, 4):
                yield address


# --------------------------------------------------------------- instruction

def _sext(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def instruction_mask(word: int, address: int,
                     window_start: int, window_end: int) -> int:
    """Mask the fields that legitimately change between executable builds.

    Control flow is kept exact except for branch displacements (which move when
    code relocates). D-form/DS-form immediates are masked as well: the
    cross-build reference (01.00 signatures against the 01.06 executable) proves
    field offsets and TOC-relative displacements change even where the
    instruction sequence is identical. Opcodes and register fields - what
    actually identifies the code - stay exact, and the window is grown until it
    is unique, so masking an immediate does not weaken identification.
    """
    primary = word >> 26
    mask = MASK_ALL
    if primary == PRIMARY_B:
        mask &= ~MASK_BRANCH_LI & MASK_ALL
    elif primary == PRIMARY_BC:
        target = address + _sext((word >> 2) & 0x3FFF, 14) * 4
        if not window_start <= target < window_end:
            mask &= ~MASK_BD & MASK_ALL
    elif primary in (PRIMARY_ADDIS, PRIMARY_ADDI, PRIMARY_ORI):
        mask &= ~0xFFFF & MASK_ALL
    elif primary in PRIMARY_LOAD_STORE_D:
        mask &= ~0xFFFF & MASK_ALL
    elif primary in PRIMARY_LOAD_STORE_DS:
        mask &= ~MASK_DS & MASK_ALL
    return mask


# ------------------------------------------------------------------ signature

@dataclass(frozen=True)
class SignatureEntry:
    relative: int      # instruction index relative to the site
    word: int
    mask: int

    def matches(self, word: int) -> bool:
        return (word ^ self.word) & self.mask == 0


@dataclass(frozen=True)
class WindowSignature:
    site_index: int
    entries: tuple[SignatureEntry, ...]

    @property
    def size(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class PatchSiteSignature:
    label: str
    address: int
    original: int
    replacement: int
    window: WindowSignature
    target: WindowSignature | None = None

    @property
    def is_branch(self) -> bool:
        return self.target is not None

    @property
    def recomputes_branch(self) -> bool:
        return self.target is not None and \
            (self.replacement >> 26) == PRIMARY_B


@dataclass(frozen=True)
class PatchSetSignature:
    name: str
    title_version: str
    games: tuple[tuple[str, tuple[str, ...]], ...]
    author: str
    notes: str
    patch_version: str
    sites: tuple[PatchSiteSignature, ...]

    def without(self, *labels: str) -> "PatchSetSignature":
        return replace(
            self,
            sites=tuple(site for site in self.sites
                        if site.label not in labels),
        )


def build_window(elf: ElfImage, address: int, size: int) -> WindowSignature:
    before = size // 2
    return build_window_around(elf, address, before, size - 1 - before)


def build_window_around(elf: ElfImage, address: int, before: int,
                        after: int) -> WindowSignature:
    """Build a window with ``before``/``after`` instructions around the site."""
    start = address - before * 4
    end = address + (after + 1) * 4
    entries = []
    for index in range(-before, after + 1):
        instruction_address = address + index * 4
        word = elf.load_word(instruction_address)
        if word is None:
            raise ValueError(
                f"instruction window for 0x{address:08X} leaves the "
                "loadable executable")
        entries.append(SignatureEntry(
            index, word,
            instruction_mask(word, instruction_address, start, end)))
    return WindowSignature(before, tuple(entries))


def locate(elf: ElfImage, signature: WindowSignature) -> list[int]:
    """Return every site address where the masked window matches."""
    # Anchor on a fully unmasked instruction so the search is a fast byte scan
    # instead of inspecting millions of words.
    anchor = next(
        (entry for entry in signature.entries if entry.mask == MASK_ALL),
        None,
    )
    matches: list[int] = []
    if anchor is not None:
        pattern = struct.pack(">I", anchor.word)
        for segment in elf.executable_segments():
            blob = elf.data[segment.offset:segment.offset + segment.filesz]
            position = blob.find(pattern)
            while position != -1:
                if position % 4 == 0:
                    site = (segment.vaddr + position
                            - anchor.relative * 4)
                    if _window_matches(elf, signature, site):
                        matches.append(site)
                position = blob.find(pattern, position + 4)
    else:  # No fully stable instruction: fall back to a full scan.
        for site in elf.executable_addresses():
            if _window_matches(elf, signature, site):
                matches.append(site)
    return sorted(set(matches))


def _window_matches(elf: ElfImage, signature: WindowSignature,
                    site: int) -> bool:
    for entry in signature.entries:
        word = elf.load_word(site + entry.relative * 4)
        if word is None or not entry.matches(word):
            return False
    return True


def _signed_displacement(reference_word: int, site: int, target: int) -> int:
    if reference_word & 2:  # AA: absolute address
        return target
    return target - site


def _branch_destination(word: int, address: int) -> int | None:
    """Absolute destination encoded by a b/bl or bc instruction."""
    primary = word >> 26
    if primary == PRIMARY_B:
        displacement = _sext(word & MASK_BRANCH_LI, 26)
    elif primary == PRIMARY_BC:
        displacement = _sext((word >> 2) & 0x3FFF, 14) * 4
    else:
        return None
    if word & 2:  # AA: absolute address
        return displacement & 0xFFFFFFFF
    return (address + displacement) & 0xFFFFFFFF


def _encode_branch(replacement: int, site: int, target: int) -> int:
    displacement = _signed_displacement(replacement, site, target)
    if displacement & 3:
        raise PatchResolutionError(
            "branch target is not four-byte aligned")
    if not -(1 << 25) <= displacement < (1 << 25):
        raise PatchResolutionError("branch displacement does not fit 26 bits")
    return (replacement & 0xFC000003) | (displacement & MASK_BRANCH_LI)


class PatchResolutionError(RuntimeError):
    """One or more sites could not be located unambiguously."""

    def __init__(self, failures):
        if isinstance(failures, str):
            failures = [failures]
        self.failures = tuple(failures)
        super().__init__("; ".join(self.failures))


@dataclass(frozen=True)
class ResolvedSite:
    label: str
    address: int
    word: int
    original_word: int
    replacement_word: int
    target_address: int | None
    reference_address: int
    window_size: int
    matches: int


@dataclass(frozen=True)
class ResolvedPatch:
    patch_set: PatchSetSignature
    sites: tuple[ResolvedSite, ...]


def resolve_site(elf: ElfImage, site: PatchSiteSignature) -> ResolvedSite:
    """Locate one site; raise when it is missing, ambiguous or corrupt."""
    window_matches = locate(elf, site.window)
    if not window_matches:
        raise PatchResolutionError(
            f"{site.label}: signature not found in this executable")
    if len(window_matches) > 1:
        addresses = ", ".join(f"0x{value:08X}" for value in window_matches)
        raise PatchResolutionError(
            f"{site.label}: signature matched {len(window_matches)} sites "
            f"({addresses}); refusing to guess")
    address = window_matches[0]
    word = elf.load_word(address)
    if word is None:
        raise PatchResolutionError(
            f"{site.label}: located address 0x{address:08X} is unreadable")
    target_address = None
    if site.is_branch:
        if site.target is None:
            raise PatchResolutionError(
                f"{site.label}: branch site has no target signature")
        target_matches = locate(elf, site.target)
        if len(target_matches) != 1:
            raise PatchResolutionError(
                f"{site.label}: branch target signature matched "
                f"{len(target_matches)} sites; refusing to guess")
        target_address = target_matches[0]
        original_primary = site.original >> 26
        if (word >> 26) != original_primary \
                or (word & 3) != (site.original & 3):
            raise PatchResolutionError(
                f"{site.label}: located instruction is not the expected "
                "branch")
        if site.recomputes_branch:
            try:
                replacement = _encode_branch(site.replacement, address,
                                             target_address)
            except PatchResolutionError as error:
                raise PatchResolutionError(
                    f"{site.label}: 0x{address:08X}: {error}") from error
        else:
            # The replacement is a nop/mov, so only prove the located branch
            # still leads to the reference target (a relocated displacement
            # is fine; a different target is not).
            destination = _branch_destination(word, address)
            if destination != target_address:
                raise PatchResolutionError(
                    f"{site.label}: branch at 0x{address:08X} points to "
                    f"0x{destination:08X}, expected 0x{target_address:08X}")
            replacement = site.replacement
    else:
        # The window may mask immediates so it can be found after relocation,
        # but the patched word itself must be exactly the reference original.
        # A non-branch replacement is written verbatim and can embed a struct
        # offset (recruit: stb r0,0x22(r9)); if the variant's immediate
        # differs, writing the reference word would target a different field.
        if word != site.original:
            raise PatchResolutionError(
                f"{site.label}: word at 0x{address:08X} is 0x{word:08X}, "
                f"expected exactly 0x{site.original:08X}; refusing to write a "
                "replacement whose fields may not apply to this executable")
        replacement = site.replacement
    return ResolvedSite(
        label=site.label,
        address=address,
        word=replacement,
        original_word=site.original,
        replacement_word=replacement,
        target_address=target_address,
        reference_address=site.address,
        window_size=site.window.size,
        matches=len(window_matches),
    )


def resolve(elf_bytes: bytes, patch_set: PatchSetSignature) -> ResolvedPatch:
    """Resolve every site; any failure refuses the whole patch set."""
    elf = ElfImage(elf_bytes)
    failures: list[str] = []
    sites: list[ResolvedSite] = []
    for site in patch_set.sites:
        try:
            sites.append(resolve_site(elf, site))
        except PatchResolutionError as error:
            failures.append(str(error))
    if failures:
        raise PatchResolutionError(failures)
    return ResolvedPatch(patch_set, tuple(sites))


# -------------------------------------------------------------- serialisation

def signature_to_dict(signature: WindowSignature) -> dict:
    return {
        "site_index": signature.site_index,
        "instructions": [
            {"relative": entry.relative, "word": entry.word,
             "mask": entry.mask}
            for entry in signature.entries
        ],
    }


def signature_from_dict(value: dict) -> WindowSignature:
    entries = tuple(
        SignatureEntry(int(item["relative"]), int(item["word"]),
                       int(item["mask"]))
        for item in value["instructions"]
    )
    return WindowSignature(int(value["site_index"]), entries)


def patch_set_to_dict(patch_set: PatchSetSignature) -> dict:
    return {
        "name": patch_set.name,
        "title_version": patch_set.title_version,
        "games": [[name, list(versions)]
                  for name, versions in patch_set.games],
        "author": patch_set.author,
        "notes": patch_set.notes,
        "patch_version": patch_set.patch_version,
        "sites": [
            {
                "label": site.label,
                "address": site.address,
                "original": site.original,
                "replacement": site.replacement,
                "window": signature_to_dict(site.window),
                "target": (signature_to_dict(site.target)
                           if site.target is not None else None),
            }
            for site in patch_set.sites
        ],
    }


def patch_set_from_dict(value: dict) -> PatchSetSignature:
    sites = []
    for item in value["sites"]:
        target = item.get("target")
        sites.append(PatchSiteSignature(
            label=item["label"],
            address=int(item["address"]),
            original=int(item["original"]),
            replacement=int(item["replacement"]),
            window=signature_from_dict(item["window"]),
            target=(signature_from_dict(target)
                    if target is not None else None),
        ))
    return PatchSetSignature(
        name=value["name"],
        title_version=value["title_version"],
        games=tuple((name, tuple(versions))
                    for name, versions in value["games"]),
        author=value["author"],
        notes=value["notes"],
        patch_version=value["patch_version"],
        sites=tuple(sites),
    )


def load_signature_database(path: Path) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "generated_from": document.get("generated_from", {}),
        "builds": {
            version: patch_set_from_dict(value)
            for version, value in document["builds"].items()
        },
    }


# ------------------------------------------------------------------- rendering

def _wrap_notes(notes: str) -> list[str]:
    import textwrap

    paragraphs = [part.strip() for part in notes.split("\n\n") if part.strip()]
    lines: list[str] = []
    for paragraph in paragraphs:
        wrapped = textwrap.wrap(
            " ".join(paragraph.split()), width=72,
            break_long_words=False, break_on_hyphens=False)
        lines.extend("      " + line for line in wrapped)
    return lines


def render_section(ppu_hash: str, resolved: ResolvedPatch) -> str:
    """Render the generated YAML section in the distributed file's style."""
    if not ppu_hash.startswith("PPU-"):
        raise ValueError("ppu_hash must include the PPU- prefix")
    patch_set = resolved.patch_set
    lines = [f"{ppu_hash}:", "", f'  "{patch_set.name}":']
    lines.append("    Games:")
    for game, versions in patch_set.games:
        lines.append(f'      "{game}":')
        lines.append(f"        NPUB30746: [ {' '.join(versions)} ]")
    lines.append(f'    Author: "{patch_set.author}"')
    lines.append("    Notes: >")
    lines.extend(_wrap_notes(patch_set.notes))
    lines.extend(_wrap_notes(
        "Addresses were located by instruction signature from the "
        f"{patch_set.title_version} reference executable, not copied. "
        "Generated for this executable's PPU hash. Experimental until a "
        "cold-boot login and native restore pass on a real variant dump."))
    lines.append(f'    Patch Version: "{patch_set.patch_version}"')
    lines.append("    Patch:")
    for site in resolved.sites:
        lines.append(
            f"      - [ be32, 0x{site.address:08X}, 0x{site.word:08X} ] "
            f"# {site.label}"
        )
    return "\n".join(lines) + "\n"


def report_json(ppu_hash: str, resolved: ResolvedPatch,
                reference_hash: str | None = None) -> dict:
    """Machine-readable evidence for a generated adaptive section."""
    return {
        "schema": 1,
        "experimental": True,
        "generated_for_ppu_hash": ppu_hash,
        "reference_title_version": resolved.patch_set.title_version,
        "reference_ppu_hash": reference_hash,
        "patch": resolved.patch_set.name,
        "resolved_sites": [
            {
                "label": site.label,
                "reference_address": f"0x{site.reference_address:08X}",
                "resolved_address": f"0x{site.address:08X}",
                "original_word": f"0x{site.original_word:08X}",
                "replacement_word": f"0x{site.word:08X}",
                "branch_target_address": (
                    f"0x{site.target_address:08X}"
                    if site.target_address is not None else None
                ),
                "window_instructions": site.window_size,
                "signature_matches": site.matches,
            }
            for site in resolved.sites
        ],
    }
