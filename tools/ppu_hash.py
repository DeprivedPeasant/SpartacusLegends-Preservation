#!/usr/bin/env python3
"""RPCS3's PPU executable hash (the ``PPU-<40 hex>`` patch-database key).

RPCS3 computes this in ``ppu_load_exec`` (rpcs3/Emu/Cell/PPUModule.cpp): one
SHA-1 over every program header in table order - the big-endian ``p_type`` and
``p_flags``, then, for a PT_LOAD header with a non-zero ``p_memsz``, the
big-endian ``p_vaddr`` and ``p_memsz`` followed by the ``p_filesz`` segment
bytes. Nothing else (no ELF header, no section headers, no zero-fill) is
included. The hash names the section RPCS3 applies patches from, so a rebuilt
EBOOT with a different hash silently receives none of them.

The input is the decrypted ELF (what ``rpcs3.exe --decrypt`` or RPCS3's
Utilities > Decrypt PS3 Binaries writes).
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
ELF_CLASS_64 = 2
ELF_DATA_BIG_ENDIAN = 2
EM_PPC64 = 21
ELF_PHDR_SIZE = 56
PT_LOAD = 1
HASH_PREFIX = "PPU-"


class ElfFormatError(ValueError):
    """The file is not an ELF that RPCS3 would accept."""


def _check_elf(elf_bytes: bytes) -> tuple[int, int, int]:
    """Validate the header fields RPCS3 needs; return (phoff, phentsize, phnum)."""
    if len(elf_bytes) < 64 or elf_bytes[:4] != ELF_MAGIC:
        raise ElfFormatError("not an ELF file")
    if elf_bytes[4] != ELF_CLASS_64:
        raise ElfFormatError("not a 64-bit ELF")
    if elf_bytes[5] != ELF_DATA_BIG_ENDIAN:
        raise ElfFormatError("not a big-endian ELF")
    machine = struct.unpack_from(">H", elf_bytes, 0x12)[0]
    if machine != EM_PPC64:
        raise ElfFormatError(f"not a PowerPC64 ELF (e_machine={machine})")
    phoff = struct.unpack_from(">Q", elf_bytes, 0x20)[0]
    phentsize = struct.unpack_from(">H", elf_bytes, 0x36)[0]
    phnum = struct.unpack_from(">H", elf_bytes, 0x38)[0]
    if phentsize != ELF_PHDR_SIZE:
        raise ElfFormatError(
            f"unexpected program-header size {phentsize} (expected "
            f"{ELF_PHDR_SIZE}); RPCS3 rejects this file")
    if phnum and phoff + phnum * phentsize > len(elf_bytes):
        raise ElfFormatError("program header table extends past end of file")
    return phoff, phentsize, phnum


def ppu_hash(elf_bytes: bytes) -> str:
    """Return RPCS3's ``PPU-<40 hex>`` executable hash."""
    phoff, phentsize, phnum = _check_elf(elf_bytes)
    digest = hashlib.sha1()
    for index in range(phnum):
        offset = phoff + index * phentsize
        (p_type, p_flags, p_offset, p_vaddr, _paddr,
         p_filesz, p_memsz, _align) = struct.unpack_from(
            ">IIQQQQQQ", elf_bytes, offset)
        digest.update(struct.pack(">I", p_type))
        digest.update(struct.pack(">I", p_flags))
        if p_type == PT_LOAD and p_memsz:
            if p_filesz > p_memsz:
                raise ElfFormatError(
                    "PT_LOAD segment has p_filesz > p_memsz; RPCS3 rejects "
                    "this file")
            end = p_offset + p_filesz
            if end > len(elf_bytes):
                raise ElfFormatError("PT_LOAD segment extends past end of file")
            digest.update(struct.pack(">Q", p_vaddr))
            digest.update(struct.pack(">Q", p_memsz))
            digest.update(elf_bytes[p_offset:end])
    return HASH_PREFIX + digest.hexdigest()


def ppu_hash_file(path: Path) -> str:
    return ppu_hash(Path(path).read_bytes())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    code = 0
    for name in argv:
        try:
            print(f"{ppu_hash_file(Path(name))}  {name}")
        except (OSError, ElfFormatError) as error:
            print(f"{name}: {error}", file=sys.stderr)
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
