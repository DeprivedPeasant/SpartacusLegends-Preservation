#!/usr/bin/env python3
"""Find Spartacus Legends in an RPCS3 folder and check its executable.

Three read-only questions, answered without the user naming any file:

- Which game install does this RPCS3 folder have (PARAM.SFO, EBOOT.BIN)?
- What is that executable's RPCS3 PPU hash, and is it covered by a supported
  patch section, an already generated (adaptive) section, or nothing yet?
  Encrypted EBOOT.BIN files are decrypted with the folder's own
  ``rpcs3.exe --decrypt`` on a temporary copy (see :mod:`eboot_source`).
- Did RPCS3 apply the compatibility patch on the last Spartacus boot? That is
  read from RPCS3's own ``log/RPCS3.log``.

The module is Qt-free so the console installer and the GUI share it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

try:
    import adaptive_patch
    import eboot_source
    import patch_installer
    import ppu_hash
except ImportError:  # Imported as tools.game_detect by the unit tests.
    from tools import adaptive_patch, eboot_source, patch_installer, ppu_hash


STATUS_SUPPORTED = "supported"
STATUS_GENERATED = "generated"
STATUS_UNKNOWN = "unknown"

LOG_NAME = "RPCS3.log"
_BOOT_RE = re.compile(r"Emulator::BootGame: .*?title_id='([^']*)'")
_HASH_RE = re.compile(
    r"PPU executable hash: (PPU-[0-9a-f]{40})(?: \(<- (\d+)\))?")
_PATH_RE = re.compile(r"SYS: Path: (.+?EBOOT\.BIN)\s*$", re.MULTILINE)

# Encrypted EBOOT.BIN files whose RPCS3 PPU hash is already known, so they
# never need rpcs3.exe --decrypt (RPCS3 v0.0.43 crashes in utils::shm::shm()
# when started only to decrypt). An EBOOT is the same file for everyone with
# the same dump. Evidence, 2026-10-29:
#   01.00 reference - rpcs3-A's log applied the 01.00 section to this EBOOT;
#                     decrypted/EBOOT.elf hashes to the same value.
#   01.06 update    - rpcs3-B's log "PPU executable hash" for this EBOOT, and
#                     the updated variant install has the identical file.
#   01.00 variant   - decrypted with rpcs3.exe and hashed; RPCS3 then applied
#                     the generated section to it (live-proven).
KNOWN_EBOOTS = {
    "836982ab540f768c61644df7b11c30b5d25dfd5f608c0954c1b1de8ae4bd1896":
        ("PPU-81471d050c14f4d20b4027686f8b571dafd32394", False),
    "68e4e95726a1ada399bb34c3d73ca8b61a50ddbd6ce836091e1cb167636d4d04":
        ("PPU-131aece6ae8526d13307be925f48c87f73c43799", False),
    "3078049d5805d147db3ac3218615afae7d0d1486d58bf46f8420845d0f75c327":
        ("PPU-af74addba068e9fd8ac2636ecca9bcdfb991ab4c", True),
}

_APPLIED_RE = re.compile(
    r"PAT: Applied patch \(hash='(PPU-[0-9a-f]{40})', description='([^']*)'"
    r".*?\(<- (\d+)\)")


class DetectionError(RuntimeError):
    """The RPCS3 folder or the game inside it could not be inspected."""


class RPCS3RunningError(DetectionError):
    """Decryption needs rpcs3.exe, which will not run beside an open RPCS3."""


RPCS3_RUNNING_MESSAGE = (
    "RPCS3 is open. Its rpcs3.exe cannot decrypt a copy of the game's "
    "executable while another RPCS3 is running - close RPCS3, then check "
    "again.")


@dataclass(frozen=True)
class GameInstall:
    rpcs3_root: Path
    game_dir: Path
    sfo_path: Path
    title_id: str
    title: str
    app_version: str
    sfo_version: str
    eboot_path: Path | None

    @property
    def supported_version(self) -> bool:
        return self.app_version in patch_installer.SUPPORTED_BUILDS

    def describe(self) -> str:
        name = self.title or "Unknown title"
        text = f"{name} ({self.title_id or 'no title ID'}) version " \
               f"{self.app_version or 'unknown'}"
        if self.sfo_version and self.sfo_version != self.app_version:
            text += f" (PARAM.SFO VERSION {self.sfo_version})"
        return text


@dataclass(frozen=True)
class ExecutableCheck:
    game: GameInstall
    eboot_sha256: str
    ppu_hash: str
    status: str
    supported_version: str | None
    can_generate: bool
    problem: str | None
    # How the hash was obtained: "known EBOOT", "RPCS3's last boot",
    # "remembered" or "decrypted".
    basis: str = "decrypted"

    def summary(self) -> str:
        if self.status == STATUS_SUPPORTED:
            return (f"{self.ppu_hash} - the supported {self.supported_version} "
                    "executable. The shipped patch covers it.")
        if self.status == STATUS_GENERATED:
            return (f"{self.ppu_hash} - a different dump. A patch generated "
                    "for it is installed (experimental).")
        if self.can_generate:
            return (f"{self.ppu_hash} - a different dump. Installing will "
                    "generate a matching patch for it (experimental).")
        return (f"{self.ppu_hash} - a different dump that cannot be patched "
                f"automatically: {self.problem}")


@dataclass(frozen=True)
class BootStatus:
    log_path: Path
    executable_hash: str | None
    total_writes: int | None
    compatibility_applied: bool
    compatibility_writes: int | None
    unreadable: bool = False
    eboot_path: str | None = None
    log_mtime: float | None = None

    def summary(self) -> str:
        if self.unreadable:
            return ("RPCS3 is open and keeps its log locked, so the last boot "
                    "cannot be read yet. Close RPCS3, then check again.")
        if self.executable_hash is None:
            return ("RPCS3's log has a Spartacus Legends boot but no executable "
                    "hash line yet.")
        if self.compatibility_applied:
            return (f"Last boot: the compatibility patch was applied to "
                    f"{self.executable_hash} "
                    f"({self.compatibility_writes} writes).")
        return (f"Last boot: {self.executable_hash} started WITHOUT the "
                "compatibility patch.")


# -------------------------------------------------------------- the game

def detect_game(rpcs3_folder: Path) -> GameInstall | None:
    """Return the Spartacus Legends install RPCS3 knows about, or None."""
    root = patch_installer.find_rpcs3_root(Path(rpcs3_folder))
    sfo = patch_installer.find_param_sfo(root)
    if sfo is None:
        return None
    try:
        fields = patch_installer.read_param_sfo(sfo)
    except (OSError, ValueError) as error:
        raise DetectionError(f"could not read {sfo}: {error}") from error
    eboot = sfo.parent / "USRDIR" / "EBOOT.BIN"
    return GameInstall(
        rpcs3_root=root,
        game_dir=sfo.parent,
        sfo_path=sfo,
        title_id=fields.get("TITLE_ID", ""),
        title=fields.get("TITLE", ""),
        app_version=fields.get("APP_VER") or fields.get("VERSION", ""),
        sfo_version=fields.get("VERSION", ""),
        eboot_path=eboot if eboot.is_file() else None,
    )


# --------------------------------------------------------- the executable

def _installed_patch_text(root: Path) -> str:
    path = root / "patches" / "imported_patch.yml"
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def known_hashes() -> dict[str, str]:
    """PPU hash (no colon) -> supported title version."""
    return {header.rstrip(":"): version
            for version, header in patch_installer.SUPPORTED_BUILDS.items()}


def _cache_key(eboot_sha256: str, title_version: str) -> str:
    """Cache entries are only valid for one EBOOT, build and signature DB."""
    database = patch_installer.supplied_signature_path()
    try:
        database_hash = hashlib.sha256(database.read_bytes()).hexdigest()[:16]
    except OSError:
        database_hash = "none"
    return f"{eboot_sha256}:{title_version}:{database_hash}"


def _same_file(left, right) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def check_executable(game: GameInstall, *, source: Path | None = None,
                     timeout: float = eboot_source.DECRYPT_TIMEOUT,
                     cache=None, boot=None) -> ExecutableCheck:
    """Hash the game's executable and say how it is (or would be) patched.

    ``source`` overrides the detected EBOOT.BIN, either with another
    EBOOT.BIN or with an already decrypted ELF (the manual fallback). An
    encrypted file is decrypted with the RPCS3 folder's own ``rpcs3.exe`` on
    a temporary copy.

    ``cache`` is an optional mapping (string keys and values) that remembers
    each EBOOT's result, so a known executable is reported without running
    rpcs3.exe again - including while RPCS3 is open, when it cannot run.
    """
    source = Path(source) if source is not None else game.eboot_path
    if source is None:
        raise DetectionError(
            f"the game folder {game.game_dir} has no USRDIR/EBOOT.BIN")
    raw = source.read_bytes()
    eboot_sha256 = hashlib.sha256(raw).hexdigest()
    key = _cache_key(eboot_sha256, game.app_version)
    remembered = None
    if cache is not None:
        try:
            remembered = json.loads(cache.get(key) or "null")
        except (TypeError, ValueError):
            remembered = None
    if remembered:
        return _classify(game, eboot_sha256, remembered["ppu_hash"],
                         bool(remembered["can_generate"]),
                         remembered.get("problem"), basis="remembered")
    known = KNOWN_EBOOTS.get(eboot_sha256)
    if known is not None:
        return _classify(game, eboot_sha256, known[0], known[1], None,
                         basis="known EBOOT")
    # RPCS3 logged the hash when this same EBOOT last booted. That settles a
    # supported or already patched executable; a new dump still needs the
    # decrypted code to locate its patch sites.
    if (boot is not None and boot.executable_hash and boot.eboot_path
            and _same_file(boot.eboot_path, source)
            and boot.log_mtime is not None
            and source.stat().st_mtime <= boot.log_mtime):
        logged = _classify(game, eboot_sha256, boot.executable_hash, False,
                           None, basis="RPCS3's last boot")
        if logged.status != STATUS_UNKNOWN:
            return logged

    if not raw.startswith(eboot_source.ELF_MAGIC) \
            and patch_installer.rpcs3_is_running():
        raise RPCS3RunningError(RPCS3_RUNNING_MESSAGE)
    with eboot_source.open_eboot(source, game.rpcs3_root,
                                 allow_decrypt=True,
                                 timeout=timeout) as elf_bytes:
        user_hash = ppu_hash.ppu_hash(elf_bytes)
        if user_hash in known_hashes():
            can_generate, problem = False, None
        else:
            can_generate, problem = _dry_run(elf_bytes, game.app_version)
    if cache is not None:
        cache[key] = json.dumps({"ppu_hash": user_hash,
                                 "can_generate": can_generate,
                                 "problem": problem})
    return _classify(game, eboot_sha256, user_hash, can_generate, problem)


def _classify(game: GameInstall, eboot_sha256: str, user_hash: str,
              can_generate: bool, problem: str | None,
              basis: str = "decrypted") -> ExecutableCheck:
    """Status from the hash and the currently installed patch file."""
    supported = known_hashes().get(user_hash)
    if supported is not None:
        return ExecutableCheck(game, eboot_sha256, user_hash,
                               STATUS_SUPPORTED, supported, False, None,
                               basis)
    if f"{user_hash}:" in _installed_patch_text(game.rpcs3_root):
        return ExecutableCheck(game, eboot_sha256, user_hash,
                               STATUS_GENERATED, None, True, None, basis)
    return ExecutableCheck(game, eboot_sha256, user_hash, STATUS_UNKNOWN,
                           None, can_generate, problem, basis)


def _dry_run(elf_bytes: bytes, title_version: str) -> tuple[bool, str | None]:
    """Whether every adaptive site resolves; nothing is written."""
    database_path = patch_installer.supplied_signature_path()
    if not database_path.is_file():
        return False, f"the signature database is missing: {database_path}"
    database = adaptive_patch.load_signature_database(database_path)
    patch_set = database["builds"].get(title_version)
    if patch_set is None:
        return False, f"no signatures exist for game version {title_version!r}"
    try:
        adaptive_patch.resolve(elf_bytes, patch_set)
    except adaptive_patch.PatchResolutionError as error:
        return False, str(error)
    return True, None


# ------------------------------------------------------------ the last boot

def last_boot_status(rpcs3_folder: Path) -> BootStatus | None:
    """Read RPCS3.log for the most recent Spartacus Legends boot, if any."""
    root = Path(rpcs3_folder)
    log_path = root / "log" / LOG_NAME
    if not log_path.is_file():
        log_path = root / LOG_NAME
    try:
        text = log_path.read_bytes().decode("utf-8", "replace")
        log_mtime = log_path.stat().st_mtime
    except PermissionError:
        # A running RPCS3 opens its log without sharing it.
        return BootStatus(log_path, None, None, False, None, unreadable=True)
    except OSError:
        return None
    status = parse_boot_log(text, log_path)
    if status is not None:
        status = BootStatus(status.log_path, status.executable_hash,
                            status.total_writes, status.compatibility_applied,
                            status.compatibility_writes, status.unreadable,
                            status.eboot_path, log_mtime)
    return status


def parse_boot_log(text: str, log_path: Path) -> BootStatus | None:
    """Parse one RPCS3.log; only the last NPUB30746 boot is considered."""
    boots = [(match.start(), match.group(1))
             for match in _BOOT_RE.finditer(text)]
    starts = [start for start, title in boots
              if title == patch_installer.TITLE_ID]
    if not starts:
        return None
    start = starts[-1]
    following = [s for s, _title in boots if s > start]
    section = text[start:following[0] if following else len(text)]
    executable = None
    total = None
    for match in _HASH_RE.finditer(section):
        executable = match.group(1)
        total = int(match.group(2)) if match.group(2) else None
    applied = False
    writes = None
    for match in _APPLIED_RE.finditer(section):
        if match.group(2) != patch_installer.COMPATIBILITY_PATCH:
            continue
        if executable is None or match.group(1) == executable:
            applied = True
            writes = int(match.group(3))
    eboot = None
    for match in _PATH_RE.finditer(section):
        eboot = match.group(1).strip()
    return BootStatus(log_path, executable, total, applied, writes,
                      eboot_path=eboot)
