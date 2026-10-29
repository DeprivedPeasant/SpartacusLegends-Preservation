"""RPCS3 PPU hash reproduction.

The two real hashes are checked against the decrypted EBOOTs when they are
present (they are local evidence, so CI skips). Synthetic ELFs pin the exact
field set - including the easy-to-miss non-LOAD headers - without depending on
game data.
"""

import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import ppu_hash

KNOWN = {
    ROOT / "decrypted" / "EBOOT.elf":
        "PPU-81471d050c14f4d20b4027686f8b571dafd32394",
    ROOT / "decrypted" / "EBOOT-1.06.elf":
        "PPU-131aece6ae8526d13307be925f48c87f73c43799",
}

HEADER_SIZE = 64
PHDR_SIZE = 56


def build_elf(segments, *, machine=21, entry=0x10000, pad_before_data=0):
    """Build a minimal big-endian ELF64 with the supplied program headers."""
    payload = b""
    headers = b""
    data_start = HEADER_SIZE + len(segments) * PHDR_SIZE + pad_before_data
    for segment in segments:
        data = segment.get("data", b"")
        offset = data_start + len(payload)
        headers += struct.pack(
            ">IIQQQQQQ",
            segment.get("type", 1),
            segment.get("flags", 5),
            offset,
            segment.get("vaddr", 0x10000),
            0,
            len(data),
            segment.get("memsz", len(data)),
            segment.get("align", 0x1000),
        )
        payload += data
    header = bytearray(HEADER_SIZE)
    header[:4] = b"\x7fELF"
    header[4] = 2       # ELFCLASS64
    header[5] = 2       # ELFDATA2MSB
    header[6] = 1       # EV_CURRENT
    struct.pack_into(">H", header, 0x12, machine)
    struct.pack_into(">I", header, 0x18, entry)
    struct.pack_into(">Q", header, 0x20, HEADER_SIZE)
    struct.pack_into(">H", header, 0x34, HEADER_SIZE)
    struct.pack_into(">H", header, 0x36, PHDR_SIZE)
    struct.pack_into(">H", header, 0x38, len(segments))
    return bytes(header) + headers + b"\x00" * pad_before_data + payload


class KnownHashTests(unittest.TestCase):
    def test_both_reference_elves_reproduce_rpcs3_hashes(self):
        missing = [str(path) for path in KNOWN if not path.is_file()]
        if missing:
            self.skipTest("decrypted reference ELFs absent: " + ", ".join(missing))
        for path, expected in KNOWN.items():
            with self.subTest(path=path.name):
                self.assertEqual(ppu_hash.ppu_hash_file(path), expected)

    def test_hash_has_the_ppu_prefix_and_lowercase_hex(self):
        path = next((path for path in KNOWN if path.is_file()), None)
        if path is None:
            self.skipTest("decrypted reference ELFs absent")
        value = ppu_hash.ppu_hash_file(path)
        self.assertTrue(value.startswith("PPU-"))
        self.assertEqual(len(value), 4 + 40)
        self.assertRegex(value[4:], r"^[0-9a-f]{40}$")


class FieldSetTests(unittest.TestCase):
    def test_non_load_program_headers_also_contribute(self):
        first = build_elf([{"data": b"AAAA"},
                           {"type": 0x60000001, "data": b""}])
        second = build_elf([{"data": b"AAAA"},
                            {"type": 0x60000002, "data": b""}])
        self.assertNotEqual(ppu_hash.ppu_hash(first),
                            ppu_hash.ppu_hash(second))

    def test_load_header_with_zero_memsz_contributes_no_data(self):
        first = build_elf([{"data": b"AAAA", "memsz": 0}])
        second = build_elf([{"data": b"BBBB", "memsz": 0}])
        self.assertEqual(ppu_hash.ppu_hash(first), ppu_hash.ppu_hash(second))

    def test_segment_bytes_are_hashed(self):
        first = build_elf([{"data": b"AAAA"}])
        second = build_elf([{"data": b"AAAB"}])
        self.assertNotEqual(ppu_hash.ppu_hash(first),
                            ppu_hash.ppu_hash(second))

    def test_entry_point_is_not_hashed(self):
        first = build_elf([{"data": b"AAAA"}], entry=0x10000)
        second = build_elf([{"data": b"AAAA"}], entry=0xDEADBEEF)
        self.assertEqual(ppu_hash.ppu_hash(first), ppu_hash.ppu_hash(second))

    def test_segment_file_offset_is_not_hashed(self):
        first = build_elf([{"data": b"AAAA"}])
        second = build_elf([{"data": b"AAAA"}], pad_before_data=0x40)
        self.assertEqual(ppu_hash.ppu_hash(first), ppu_hash.ppu_hash(second))

    def test_vaddr_and_memsz_are_hashed(self):
        base = build_elf([{"data": b"AAAA", "vaddr": 0x10000}])
        moved = build_elf([{"data": b"AAAA", "vaddr": 0x20000}])
        bigger = build_elf([{"data": b"AAAA", "memsz": 8}])
        self.assertNotEqual(ppu_hash.ppu_hash(base), ppu_hash.ppu_hash(moved))
        self.assertNotEqual(ppu_hash.ppu_hash(base), ppu_hash.ppu_hash(bigger))

    def test_matches_an_explicit_construction(self):
        # Independent of the implementation: hash fields in phdr order.
        elf = build_elf([
            {"type": 1, "flags": 5, "data": b"abcd", "vaddr": 0x100000},
            {"type": 7, "flags": 4, "data": b""},
            {"type": 1, "flags": 6, "data": b"", "memsz": 0},
        ])
        digest = hashlib.sha1()
        digest.update(struct.pack(">II", 1, 5))
        digest.update(struct.pack(">QQ", 0x100000, 4))
        digest.update(b"abcd")
        digest.update(struct.pack(">II", 7, 4))
        digest.update(struct.pack(">II", 1, 6))
        self.assertEqual(ppu_hash.ppu_hash(elf), "PPU-" + digest.hexdigest())


class RejectionTests(unittest.TestCase):
    def test_not_an_elf(self):
        with self.assertRaises(ppu_hash.ElfFormatError):
            ppu_hash.ppu_hash(b"SCE\0not an elf")

    def test_elf32_is_rejected(self):
        elf = bytearray(build_elf([{"data": b"AAAA"}]))
        elf[4] = 1
        with self.assertRaises(ppu_hash.ElfFormatError):
            ppu_hash.ppu_hash(bytes(elf))

    def test_little_endian_is_rejected(self):
        elf = bytearray(build_elf([{"data": b"AAAA"}]))
        elf[5] = 1
        with self.assertRaises(ppu_hash.ElfFormatError):
            ppu_hash.ppu_hash(bytes(elf))

    def test_wrong_program_header_size_is_rejected(self):
        elf = bytearray(build_elf([{"data": b"AAAA"}]))
        struct.pack_into(">H", elf, 0x36, 32)
        with self.assertRaises(ppu_hash.ElfFormatError):
            ppu_hash.ppu_hash(bytes(elf))

    def test_filesz_larger_than_memsz_is_rejected(self):
        elf = build_elf([{"data": b"AAAA", "memsz": 2}])
        with self.assertRaises(ppu_hash.ElfFormatError):
            ppu_hash.ppu_hash(elf)

    def test_truncated_segment_is_rejected(self):
        elf = build_elf([{"data": b"AAAA"}])
        with self.assertRaises(ppu_hash.ElfFormatError):
            ppu_hash.ppu_hash(elf[:-2])

    def test_cli_prints_hash_and_reports_bad_file(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "good.elf"
            good.write_bytes(build_elf([{"data": b"AAAA"}]))
            bad = Path(directory) / "bad.bin"
            bad.write_bytes(b"not an elf")
            output = []
            with mock.patch("builtins.print",
                            new=lambda *args, **kwargs:
                            output.append(" ".join(map(str, args)))):
                self.assertEqual(ppu_hash.main([str(good)]), 0)
                self.assertEqual(ppu_hash.main([str(bad)]), 1)
        self.assertTrue(any(value.startswith("PPU-") for value in output))
        self.assertTrue(any("bad.bin" in value for value in output))


if __name__ == "__main__":
    unittest.main()
