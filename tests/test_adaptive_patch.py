"""Adaptive patch signatures: resolution, cross-build, render and installer.

The synthetic ELF tests build an in-memory executable from the stored signature
windows, so duplication/corruption/relocation are exercised without needing the
game's decrypted EBOOTs. The reference-ELF tests skip when decrypted/ is absent.
"""

import dataclasses
import functools
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import adaptive_patch
import ppu_hash
from tools.patch_installer import (
    COMPATIBILITY_PATCH, install_setup, parse_args, verify_setup)

DB_PATH = TOOLS / "patch_signatures.json"
ELVES = {
    "01.00": ROOT / "decrypted" / "EBOOT.elf",
    "01.06": ROOT / "decrypted" / "EBOOT-1.06.elf",
}
TITLE_ID = "NPUB30746"


def load_database():
    return adaptive_patch.load_signature_database(DB_PATH)


def site_by_label(patch_set, label):
    return next(site for site in patch_set.sites if site.label == label)


def only(patch_set, *labels):
    return dataclasses.replace(
        patch_set,
        sites=tuple(site for site in patch_set.sites
                    if site.label in labels),
    )


def build_elf_from_words(words: dict[int, int]) -> bytes:
    """One PT_LOAD segment holding the supplied virtual-address words."""
    start = min(words)
    end = max(words) + 4
    payload = bytearray(end - start)
    for address, word in words.items():
        struct.pack_into(">I", payload, address - start, word)
    offset = 0x1000
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 2
    header[6] = 1
    struct.pack_into(">H", header, 0x12, 21)       # EM_PPC64
    struct.pack_into(">Q", header, 0x20, 64)       # e_phoff
    struct.pack_into(">H", header, 0x34, 64)       # e_ehsize
    struct.pack_into(">H", header, 0x36, 56)       # e_phentsize
    struct.pack_into(">H", header, 0x38, 1)        # e_phnum
    phdr = struct.pack(">IIQQQQQQ", 1, 5, offset, start, 0,
                       len(payload), len(payload), 0x1000)
    padding = b"\x00" * (offset - len(header) - len(phdr))
    return bytes(header) + phdr + padding + bytes(payload)


def synthetic_elf(site, *, target_shift=0, duplicate=False, corrupt=False,
                  base=0x100000, target_base=0x200000):
    """Build an in-memory ELF containing just this site (and its target)."""
    site_address = base + site.window.site_index * 4
    words: dict[int, int] = {}
    for entry in site.window.entries:
        words[site_address + entry.relative * 4] = entry.word
    words[site_address] = site.original
    target_address = None
    if site.target is not None:
        target_address = target_base + target_shift
        for entry in site.target.entries:
            words[target_address + entry.relative * 4] = entry.word
    if duplicate:
        duplicate_base = target_base + 0x100000
        duplicated_site = duplicate_base + site.window.site_index * 4
        for entry in site.window.entries:
            words[duplicated_site + entry.relative * 4] = entry.word
        words[duplicated_site] = site.original
    if corrupt:
        words[site_address] = site.original ^ 0x00200000
    return build_elf_from_words(words), site_address, target_address


class ReferenceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.database = load_database()
        missing = [str(path) for path in ELVES.values() if not path.is_file()]
        if missing:
            self.skipTest("decrypted reference ELFs absent: "
                          + ", ".join(missing))

    def test_every_0100_site_resolves_to_its_own_reference_address(self):
        patch_set = self.database["builds"]["01.00"]
        elf = adaptive_patch.ElfImage(ELVES["01.00"].read_bytes())
        for site in patch_set.sites:
            with self.subTest(label=site.label):
                resolved = adaptive_patch.resolve_site(elf, site)
                self.assertEqual(resolved.address, site.address)
                self.assertEqual(resolved.matches, 1)
        resolved = adaptive_patch.resolve(
            ELVES["01.00"].read_bytes(), patch_set)
        self.assertEqual(
            [site.address for site in resolved.sites],
            [site.address for site in patch_set.sites],
        )

    def test_every_0106_site_resolves_to_its_own_reference_address(self):
        patch_set = self.database["builds"]["01.06"]
        elf = adaptive_patch.ElfImage(ELVES["01.06"].read_bytes())
        for site in patch_set.sites:
            with self.subTest(label=site.label):
                resolved = adaptive_patch.resolve_site(elf, site)
                self.assertEqual(resolved.address, site.address)
        resolved = adaptive_patch.resolve(
            ELVES["01.06"].read_bytes(), patch_set)
        self.assertEqual(
            [site.address for site in resolved.sites],
            [site.address for site in patch_set.sites],
        )

    def test_cross_build_0100_signatures_find_unchanged_0106_sites(self):
        patch_set = self.database["builds"]["01.00"]
        elf = adaptive_patch.ElfImage(ELVES["01.06"].read_bytes())
        expected = {
            "enter the game's state-26 success path": 0x0057BAF8,
            "supply Commerce readiness to the native save enumerator":
                0x00156DB4,
            "accept recruit-pool refresh completion": 0x001DBD34,
        }
        for label, address in expected.items():
            with self.subTest(label=label):
                site = site_by_label(patch_set, label)
                self.assertEqual(
                    adaptive_patch.locate(elf, site.window), [address])
        # The profile fallback was inverted in 01.06: its 01.00 signature must
        # not be mislocated there, and the whole-set resolver must refuse it.
        profile = site_by_label(patch_set, "apply the locally saved profile")
        self.assertEqual(adaptive_patch.locate(elf, profile.window), [])
        with self.assertRaises(adaptive_patch.PatchResolutionError) as raised:
            adaptive_patch.resolve(ELVES["01.06"].read_bytes(), patch_set)
        self.assertIn("apply the locally saved profile",
                      str(raised.exception))

    def test_generated_yaml_merges_into_the_reference_patch_file(self):
        from tools import patch_installer

        patch_set = self.database["builds"]["01.00"]
        resolved = adaptive_patch.resolve(
            ELVES["01.00"].read_bytes(), patch_set)
        user_hash = "PPU-0123456789abcdef0123456789abcdef01234567"
        section = adaptive_patch.render_section(user_hash, resolved)
        self.assertIn(f"{user_hash}:", section)
        once = patch_installer._merge_one_section(
            [], section, f"{user_hash}:")
        twice = patch_installer._merge_one_section(
            once, section, f"{user_hash}:")
        self.assertEqual(once, twice)
        self.assertEqual("\n".join(once).count(f"{user_hash}:"), 1)


class SyntheticResolutionTests(unittest.TestCase):
    def setUp(self):
        self.patch_set = load_database()["builds"]["01.00"]
        self.branch_site = site_by_label(
            self.patch_set, "enter the game's state-26 success path")
        self.plain_site = site_by_label(
            self.patch_set,
            "supply Commerce readiness to the native save enumerator")

    def test_shifted_target_recomputes_the_branch(self):
        elf_bytes, site_address, target_address = synthetic_elf(
            self.branch_site, target_shift=0x40)
        resolved = adaptive_patch.resolve(
            elf_bytes, only(self.patch_set, self.branch_site.label))
        site = resolved.sites[0]
        self.assertEqual(site.address, site_address)
        self.assertEqual(site.target_address, target_address)
        displacement = target_address - site_address
        expected = ((self.branch_site.replacement & 0xFC000003)
                    | (displacement & adaptive_patch.MASK_BRANCH_LI))
        self.assertEqual(site.word, expected)
        self.assertNotEqual(site.word, self.branch_site.replacement)

    def test_duplicated_signature_is_refused(self):
        elf_bytes, _site, _target = synthetic_elf(
            self.plain_site, duplicate=True)
        with self.assertRaises(adaptive_patch.PatchResolutionError) as raised:
            adaptive_patch.resolve(
                elf_bytes, only(self.patch_set, self.plain_site.label))
        message = str(raised.exception)
        self.assertIn("matched 2 sites", message)
        self.assertIn("refusing to guess", message)

    def test_corrupted_site_word_is_refused(self):
        elf_bytes, _site, _target = synthetic_elf(
            self.plain_site, corrupt=True)
        with self.assertRaises(adaptive_patch.PatchResolutionError):
            adaptive_patch.resolve(
                elf_bytes, only(self.patch_set, self.plain_site.label))

    def test_masked_immediate_change_at_a_plain_site_is_refused(self):
        # The window masks D-form immediates so it still locates the site,
        # but a replacement written verbatim (stb r0,0x22(r9)) would hit a
        # different field if the variant's offset differs. Both plain sites
        # must therefore require the exact reference word.
        for label in ("accept recruit-pool refresh completion",
                      "supply Commerce readiness to the native save enumerator"):
            with self.subTest(label=label):
                site = site_by_label(self.patch_set, label)
                elf_bytes, site_address, _target = synthetic_elf(site)
                elf = adaptive_patch.ElfImage(elf_bytes)
                changed = (site.original & 0xFFFF0000) | (
                    (site.original + 4) & 0xFFFF)
                offset = next(
                    segment.offset + (site_address - segment.vaddr)
                    for segment in elf.executable_segments()
                    if segment.vaddr <= site_address
                    < segment.vaddr + segment.filesz)
                patched = bytearray(elf_bytes)
                struct.pack_into(">I", patched, offset, changed)
                patched = bytes(patched)
                # The masked window still finds exactly this site...
                self.assertEqual(
                    adaptive_patch.locate(
                        adaptive_patch.ElfImage(patched), site.window),
                    [site_address])
                # ...but resolution refuses the inexact word.
                with self.assertRaises(
                        adaptive_patch.PatchResolutionError) as raised:
                    adaptive_patch.resolve(patched, only(self.patch_set, label))
                self.assertIn("expected exactly", str(raised.exception))

    def test_unchanged_plain_site_still_resolves_to_the_reference_word(self):
        site = site_by_label(
            self.patch_set, "accept recruit-pool refresh completion")
        elf_bytes, site_address, _target = synthetic_elf(site)
        resolved = adaptive_patch.resolve(elf_bytes, only(self.patch_set,
                                                          site.label))
        self.assertEqual(resolved.sites[0].address, site_address)
        self.assertEqual(resolved.sites[0].word, site.replacement)

    def test_one_failure_refuses_the_whole_set(self):
        broken_bytes, _site, _target = synthetic_elf(
            self.plain_site, corrupt=True, base=0x400000)
        # Both windows are placed in one ELF: the good branch site resolves,
        # the corrupted plain site does not, so nothing may be applied.
        target_address = 0x200000
        words = {}
        branch_site_address = 0x100000 + self.branch_site.window.site_index * 4
        for entry in self.branch_site.window.entries:
            words[branch_site_address + entry.relative * 4] = entry.word
        words[branch_site_address] = self.branch_site.original
        for entry in self.branch_site.target.entries:
            words[target_address + entry.relative * 4] = entry.word
        plain_address = 0x400000 + self.plain_site.window.site_index * 4
        broken = adaptive_patch.ElfImage(broken_bytes)
        for entry in self.plain_site.window.entries:
            words[plain_address + entry.relative * 4] = (
                broken.load_word(plain_address + entry.relative * 4))
        elf_bytes = build_elf_from_words(words)
        with self.assertRaises(adaptive_patch.PatchResolutionError) as raised:
            adaptive_patch.resolve(elf_bytes, self.patch_set)
        self.assertIn(self.plain_site.label, str(raised.exception))
        # The good branch site was resolvable, but no ResolvedPatch is returned.
        self.assertIsInstance(raised.exception, adaptive_patch.PatchResolutionError)

    def test_render_section_matches_the_distributed_style(self):
        elf_bytes, site_address, _target = synthetic_elf(self.branch_site)
        resolved = adaptive_patch.resolve(
            elf_bytes, only(self.patch_set, self.branch_site.label))
        user_hash = "PPU-" + "ab" * 20
        section = adaptive_patch.render_section(user_hash, resolved)
        self.assertTrue(section.startswith(f"{user_hash}:\n"))
        self.assertIn(f'  "{COMPATIBILITY_PATCH}":', section)
        self.assertIn(f'        {TITLE_ID}: [ 01.00 ]', section)
        self.assertIn('    Patch Version: "4.2"', section)
        self.assertIn("located by instruction signature", section)
        self.assertIn("Experimental", section)
        self.assertIn(
            f"      - [ be32, 0x{site_address:08X}, "
            f"0x{resolved.sites[0].word:08X} ] # "
            f"{self.branch_site.label}",
            section,
        )

    def test_report_json_records_the_evidence(self):
        elf_bytes, site_address, target_address = synthetic_elf(
            self.branch_site)
        resolved = adaptive_patch.resolve(
            elf_bytes, only(self.patch_set, self.branch_site.label))
        report = adaptive_patch.report_json(
            "PPU-" + "cd" * 20, resolved,
            reference_hash="PPU-" + "ef" * 20)
        self.assertTrue(report["experimental"])
        self.assertEqual(report["reference_title_version"], "01.00")
        self.assertEqual(len(report["resolved_sites"]), 1)
        entry = report["resolved_sites"][0]
        self.assertEqual(entry["resolved_address"], f"0x{site_address:08X}")
        self.assertEqual(entry["branch_target_address"],
                         f"0x{target_address:08X}")
        self.assertEqual(entry["signature_matches"], 1)
        self.assertGreaterEqual(entry["window_instructions"], 16)


# --------------------------------------------------------------- installer

def write_param_sfo(path: Path, fields: dict[str, str]) -> None:
    keys = b"".join(key.encode() + b"\x00" for key in fields)
    values = b"".join(value.encode() + b"\x00" for value in fields.values())
    key_table = 20 + 16 * len(fields)
    data_table = key_table + len(keys)
    index = b""
    key_offset = data_offset = 0
    for key, value in fields.items():
        size = len(value.encode()) + 1
        index += struct.pack("<HHIII", key_offset, 0x0204, size, size,
                             data_offset)
        key_offset += len(key.encode()) + 1
        data_offset += size
    header = struct.pack("<4sIIII", b"\x00PSF", 0x00000101, key_table,
                         data_table, len(fields))
    path.write_bytes(header + index + keys + values)


def make_rpcs3_tree(root: Path, *, app_version: str = "01.00") -> Path:
    (root / "patches").mkdir(parents=True)
    (root / "config" / "custom_configs").mkdir(parents=True)
    (root / "config" / "config.yml").write_text(
        "Core:\n  PPU Decoder: Recompiler (LLVM)\nNet:\n"
        "  IP swap list: ''\n  Internet enabled: Disconnected\n"
        "  PSN status: Disconnected\n", encoding="utf-8")
    (root / "config" / "rpcn.yml").write_text(
        "Host: np.rpcs.net\nNPID: player\n", encoding="utf-8")
    game = root / "dev_hdd0" / "game" / TITLE_ID
    game.mkdir(parents=True)
    write_param_sfo(game / "PARAM.SFO",
                    {"APP_VER": app_version, "TITLE_ID": TITLE_ID,
                     "TITLE": "Spartacus Legends"})
    return root


@functools.lru_cache(maxsize=1)
def unprotected_variant_elf() -> bytes | None:
    """Reference 01.00 ELF with one byte changed outside every signature.

    Built once per test run: each call copies and hashes the 9 MB executable,
    and several tests use it (a MemoryError appeared under memory pressure).
    """
    if not ELVES["01.00"].is_file():
        return None
    reference = ELVES["01.00"].read_bytes()
    reference_hash = ppu_hash.ppu_hash(reference)
    data = bytearray(reference)
    patch_set = load_database()["builds"]["01.00"]
    elf = adaptive_patch.ElfImage(bytes(data))
    protected: set[int] = set()
    for site in patch_set.sites:
        for entry in site.window.entries:
            protected.add(site.address + entry.relative * 4)
        if site.target is not None:
            target = adaptive_patch._branch_destination(
                site.original, site.address)
            for entry in site.target.entries:
                protected.add(target + entry.relative * 4)
    for segment in elf.executable_segments():
        for address in range(segment.vaddr + 0x100,
                             segment.vaddr + segment.filesz, 4):
            if address in protected:
                continue
            offset = segment.offset + (address - segment.vaddr)
            data[offset] ^= 0x01
            if ppu_hash.ppu_hash(bytes(data)) != reference_hash:
                return bytes(data)
            data[offset] ^= 0x01
    return None


class InstallerAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)
        from test_patch_installer import pin_medium_integrity
        pin_medium_integrity(self)

    def test_known_hash_adaptive_mode_changes_nothing(self):
        if not ELVES["01.00"].is_file():
            self.skipTest("decrypted reference ELF absent")
        root_a = make_rpcs3_tree(self.workspace / "plain" / "RPCS3")
        root_b = make_rpcs3_tree(self.workspace / "adaptive" / "RPCS3")
        plain = install_setup(root_a, self.workspace / "plain" / "release")
        adaptive = install_setup(
            root_b, self.workspace / "adaptive" / "release",
            eboot=ELVES["01.00"], adaptive=True)
        self.assertIsNone(adaptive.adaptive_report)
        self.assertEqual(adaptive.adaptive_hash,
                         "PPU-81471d050c14f4d20b4027686f8b571dafd32394")
        self.assertEqual(
            plain.imported_patch.read_text(encoding="utf-8"),
            adaptive.imported_patch.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            plain.patch_config.read_text(encoding="utf-8"),
            adaptive.patch_config.read_text(encoding="utf-8"),
        )

    def test_unknown_hash_generates_an_idempotent_section_and_report(self):
        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        elf_path = self.workspace / "variant.elf"
        elf_path.write_bytes(variant)
        variant_hash = ppu_hash.ppu_hash(variant)
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        server = self.workspace / "release"
        result = install_setup(
            root, server, eboot=elf_path, adaptive=True)
        self.assertEqual(result.adaptive_hash, variant_hash)
        self.assertIsNotNone(result.adaptive_report)
        imported = result.imported_patch.read_text(encoding="utf-8")
        self.assertIn(f"{variant_hash}:", imported)
        self.assertEqual(imported.count(f"{variant_hash}:"), 1)
        patch_config = result.patch_config.read_text(encoding="utf-8")
        self.assertIn(variant_hash, patch_config)
        self.assertIn("        Enabled: true", patch_config)
        report = json.loads(
            result.adaptive_report.read_text(encoding="utf-8"))
        self.assertEqual(report["generated_for_ppu_hash"], variant_hash)
        self.assertTrue(report["experimental"])
        self.assertEqual(len(report["resolved_sites"]), 4)

        second = install_setup(root, server, eboot=elf_path, adaptive=True)
        self.assertEqual(
            imported, second.imported_patch.read_text(encoding="utf-8"))
        self.assertEqual(
            patch_config,
            second.patch_config.read_text(encoding="utf-8"))
        self.assertEqual(second.backups, ())
        self.assertEqual(second.adaptive_report, result.adaptive_report)

    def test_unresolvable_variant_is_refused_before_any_write(self):
        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        data = bytearray(variant)
        patch_set = load_database()["builds"]["01.00"]
        site = site_by_label(
            patch_set,
            "supply Commerce readiness to the native save enumerator")
        elf = adaptive_patch.ElfImage(bytes(data))
        for segment in elf.segments:
            if segment.vaddr <= site.address < segment.vaddr + segment.filesz:
                offset = segment.offset + (site.address - segment.vaddr)
                data[offset] ^= 0x01
                break
        elf_path = self.workspace / "broken.elf"
        elf_path.write_bytes(bytes(data))
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        with self.assertRaises(adaptive_patch.PatchResolutionError):
            install_setup(root, self.workspace / "release",
                          eboot=elf_path, adaptive=True)
        self.assertFalse((root / "patches" / "imported_patch.yml").exists())
        self.assertFalse((root / "config" / "patch_config.yml").exists())

    def test_verify_reports_coverage_for_the_supplied_elf(self):
        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        elf_path = self.workspace / "variant.elf"
        elf_path.write_bytes(variant)
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        server = self.workspace / "release"
        install_setup(root, server)
        before = [message for passed, message, required
                  in verify_setup(root, server, eboot_elf=elf_path)
                  if not passed and not required]
        self.assertTrue(any("is not covered" in message for message in before))
        install_setup(root, server, eboot=elf_path, adaptive=True)
        after = [message for passed, message, required
                 in verify_setup(root, server, eboot_elf=elf_path)
                 if not passed and not required]
        self.assertEqual(after, [])

    def test_verify_explains_a_non_elf_file(self):
        encrypted = self.workspace / "EBOOT.BIN"
        encrypted.write_bytes(b"SCE\0encrypted")
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        server = self.workspace / "release"
        install_setup(root, server)
        messages = [message for passed, message, required
                    in verify_setup(root, server, eboot_elf=encrypted)
                    if not passed and not required]
        self.assertTrue(any("not a decrypted ELF" in message
                            for message in messages))

    def test_adaptive_cli_flags_and_validation(self):
        with mock.patch.object(sys, "argv", ["patch_installer.py",
                                             "--adaptive"]):
            args = parse_args()
        self.assertTrue(args.adaptive)
        self.assertIsNone(args.eboot)
        self.assertIsNone(args.eboot_elf)
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        server = self.workspace / "release"
        # Every run goes through the sandboxed helper so a regression that
        # reaches the install step still cannot write the repo's data/.
        # No EBOOT.BIN in the tree and none given: --adaptive cannot work.
        code, _output = self._run_cli(
            self._cli_namespace(root, adaptive=True), server)
        self.assertEqual(code, 2)
        # Contradictory flags are refused before anything is inspected.
        code, _output = self._run_cli(
            self._cli_namespace(root, adaptive=True, no_adaptive=True),
            server)
        self.assertEqual(code, 2)
        code, _output = self._run_cli(
            self._cli_namespace(root, eboot=self.workspace / "EBOOT.BIN",
                                eboot_elf=self.workspace / "EBOOT.elf"),
            server)
        self.assertEqual(code, 2)
        self.assertFalse((server / "data").exists())

    def _cli_namespace(self, root, **overrides):
        namespace = mock.Mock()
        namespace.rpcs3_folder = str(root)
        namespace.verify = False
        namespace.eboot = None
        namespace.eboot_elf = None
        namespace.adaptive = False
        namespace.no_adaptive = False
        namespace.no_hash_check = False
        namespace.allow_unused_folder = False
        namespace.title_version = None
        namespace.yes = True
        namespace.no_wait = True
        for key, value in overrides.items():
            setattr(namespace, key, value)
        return namespace

    def _run_cli(self, namespace, server):
        from tools import patch_installer
        patch_file = patch_installer.supplied_patch_path()
        signatures = patch_installer.supplied_signature_path()
        # application_dir decides where server-config.json is written; point
        # it at the temp release folder, keeping the shipped inputs readable.
        with mock.patch.object(patch_installer, "rpcs3_is_running",
                               return_value=False), \
                mock.patch.object(patch_installer, "application_dir",
                                  return_value=server), \
                mock.patch.object(patch_installer, "supplied_patch_path",
                                  return_value=patch_file), \
                mock.patch.object(patch_installer, "supplied_signature_path",
                                  return_value=signatures), \
                mock.patch("builtins.print") as printed:
            code = patch_installer.run(namespace)
        output = "\n".join(" ".join(str(arg) for arg in call.args)
                            for call in printed.call_args_list)
        return code, output

    def test_cli_detects_a_different_dump_and_generates_its_patch(self):
        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        usrdir = root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
        usrdir.mkdir()
        # A decrypted EBOOT needs no rpcs3.exe; the flow is otherwise real.
        (usrdir / "EBOOT.BIN").write_bytes(variant)
        server = self.workspace / "release"
        code, output = self._run_cli(self._cli_namespace(root), server)
        variant_hash = ppu_hash.ppu_hash(variant)
        self.assertIn("different dump", output)
        self.assertIn(variant_hash, output)
        imported = (root / "patches" / "imported_patch.yml").read_text(
            encoding="utf-8")
        self.assertEqual(imported.count(f"{variant_hash}:"), 1)
        self.assertTrue((root / "patches" /
                         f"adaptive-patch-{variant_hash}-report.json")
                        .is_file())
        self.assertIn(f"Executable hash {variant_hash} is covered", output)
        # A second run keeps the generated section without duplicating it.
        self._run_cli(self._cli_namespace(root), server)
        imported = (root / "patches" / "imported_patch.yml").read_text(
            encoding="utf-8")
        self.assertEqual(imported.count(f"{variant_hash}:"), 1)
        self.assertNotEqual(code, 2)

    def test_cli_no_adaptive_reports_an_unpatched_dump(self):
        variant = unprotected_variant_elf()
        if variant is None:
            self.skipTest("decrypted reference ELF absent")
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        usrdir = root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
        usrdir.mkdir()
        (usrdir / "EBOOT.BIN").write_bytes(variant)
        code, output = self._run_cli(
            self._cli_namespace(root, no_adaptive=True),
            self.workspace / "release")
        self.assertEqual(code, 1)
        imported = (root / "patches" / "imported_patch.yml").read_text(
            encoding="utf-8")
        self.assertNotIn(ppu_hash.ppu_hash(variant), imported)

    def test_cli_supported_executable_installs_only_the_shipped_patch(self):
        if not ELVES["01.00"].is_file():
            self.skipTest("decrypted reference ELF absent")
        root = make_rpcs3_tree(self.workspace / "RPCS3")
        usrdir = root / "dev_hdd0" / "game" / TITLE_ID / "USRDIR"
        usrdir.mkdir()
        (usrdir / "EBOOT.BIN").write_bytes(ELVES["01.00"].read_bytes())
        code, output = self._run_cli(self._cli_namespace(root),
                                     self.workspace / "release")
        self.assertIn("the supported 01.00 executable", output)
        self.assertFalse(list((root / "patches").glob("adaptive-patch-*")))


if __name__ == "__main__":
    unittest.main()
