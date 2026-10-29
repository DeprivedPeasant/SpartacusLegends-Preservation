#!/usr/bin/env python3
"""Obtain a decrypted ELF for the installed EBOOT.

Two paths, both explicit:

1. The user picked a file that already starts with the ELF magic (for example
   the output of RPCS3's Utilities > Decrypt PS3 Binaries). It is used as-is.
2. The user picked ``EBOOT.BIN`` and supplied the RPCS3 folder *and* asked for
   decryption. The encrypted file is copied into a fresh temporary directory
   and ``rpcs3.exe --decrypt <copy>`` is run there (time-bounded). RPCS3 writes
   the decrypted ``.elf`` beside the copy; the caller receives its bytes while
   the temporary directory still exists and it is removed afterwards.

Nothing here implements NPDRM/SELF crypto and no keys are shipped. Decryption
always runs on a copy, never inside the user's game folder.

Running ``rpcs3.exe --decrypt`` starts RPCS3's logger, which rewrites
``log/RPCS3.log`` (and its ``.gz``, ``TTY.log`` and ``RPCS3.buf``). Those hold
the user's last game boot, which the setup check reads to see whether the
compatibility patch applied, so they are saved before the decrypt and put
back afterwards.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
DECRYPT_TIMEOUT = 60.0

UTILITIES_MESSAGE = (
    "This is not a decrypted ELF, so its code cannot be inspected or patched "
    "by signature. Decrypt it with RPCS3: Utilities > Decrypt PS3 Binaries, "
    "then choose the produced .elf file."
)


# RPCS3 files a --decrypt run rewrites (verified on v0.0.42), relative to the
# RPCS3 folder. Older layouts keep the log beside rpcs3.exe.
RPCS3_RUN_FILES = (
    Path("log") / "RPCS3.log",
    Path("log") / "RPCS3.log.gz",
    Path("log") / "TTY.log",
    Path("RPCS3.log"),
    Path("RPCS3.buf"),
)


# Qt settings must not leak from this process (for example the frozen GUI's
# bundled PySide6 plugin path, or an offscreen platform used for screenshots)
# into rpcs3.exe, which ships its own Qt and fails to start with "no Qt
# platform plugin could be initialized".
QT_ENVIRONMENT_PREFIXES = ("QT_", "QML", "QML2_")

# A failed RPCS3 start shows its error box from a helper process that still
# holds the log files; give it a moment to let go before restoring them.
RESTORE_ATTEMPTS = 40
RESTORE_DELAY = 0.25


# PyInstaller's one-file bootloader keeps private state in variables with
# these prefixes; an outside program has no use for them.
PYINSTALLER_ENVIRONMENT_PREFIXES = ("_PYI", "_MEIPASS")


def _bundle_dir() -> str | None:
    """The frozen application's unpack folder (``_MEIxxxx``), if any."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", None)
    return None


def rpcs3_environment(base=None, bundle_dir: str | None = None) -> dict:
    """The environment for rpcs3.exe, without anything this app added.

    Removes every Qt variable, PyInstaller's private variables, and any PATH
    entry inside the frozen application's unpack folder - otherwise rpcs3.exe
    can load this app's bundled Qt or VCRUNTIME140.dll instead of its own.
    """
    environment = dict(os.environ if base is None else base)
    bundle = bundle_dir if bundle_dir is not None else _bundle_dir()
    for name in list(environment):
        upper = name.upper()
        if upper.startswith(QT_ENVIRONMENT_PREFIXES) \
                or upper.startswith(PYINSTALLER_ENVIRONMENT_PREFIXES):
            del environment[name]
    if bundle:
        bundle_key = os.path.normcase(os.path.normpath(bundle))
        for name in list(environment):
            if name.upper() != "PATH":
                continue
            kept = [
                entry for entry in environment[name].split(os.pathsep)
                if entry and not os.path.normcase(
                    os.path.normpath(entry)).startswith(bundle_key)
            ]
            environment[name] = os.pathsep.join(kept)
    return environment


@contextmanager
def outside_program_dll_search():
    """Let a launched program find its own DLLs, not this app's bundled ones.

    The PyInstaller bootloader calls ``SetDllDirectoryW(_MEIPASS)`` and child
    processes inherit it, so rpcs3.exe loaded the bundled VCRUNTIME140.dll and
    refused to start. PyInstaller's documented remedy is to reset the DLL
    directory around the launch; it is restored afterwards for this app.
    """
    bundle = _bundle_dir()
    kernel32 = None
    if bundle and os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetDllDirectoryW(None)
        except (ImportError, AttributeError, OSError):
            kernel32 = None
    try:
        yield
    finally:
        if kernel32 is not None:
            kernel32.SetDllDirectoryW(bundle)


class EbootSourceError(RuntimeError):
    """The EBOOT could not be turned into a decrypted ELF."""


def is_elf(path: Path) -> bool:
    """True when the file really starts with the ELF magic (not XELF/SELF)."""
    try:
        with Path(path).open("rb") as stream:
            return stream.read(4) == ELF_MAGIC
    except OSError:
        return False


def find_decrypted_elf(directory: Path) -> Path | None:
    """Locate the single ``.elf`` RPCS3 produced in ``directory``."""
    candidates = sorted(
        path for path in Path(directory).rglob("*")
        if path.is_file() and path.suffix.lower() == ".elf" and is_elf(path)
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


def decrypt_with_rpcs3(eboot_path: Path, rpcs3_folder: Path,
                       timeout: float = DECRYPT_TIMEOUT) -> tuple[bytes, Path]:
    """Copy EBOOT.BIN to a temp dir and run ``rpcs3.exe --decrypt`` on it.

    Returns ``(elf_bytes, temporary_directory)``; the caller owns the directory
    and must remove it. Kept separate from :func:`open_eboot` so tests can mock
    the subprocess and inspect the copy location.
    """
    eboot_path = Path(eboot_path)
    if not eboot_path.is_file():
        raise EbootSourceError(f"EBOOT file not found: {eboot_path}")
    rpcs3_exe = Path(rpcs3_folder).expanduser().resolve() / "rpcs3.exe"
    if not rpcs3_exe.is_file():
        raise EbootSourceError(
            f"rpcs3.exe was not found in {rpcs3_folder}. Choose the RPCS3 "
            "folder that contains rpcs3.exe, or decrypt the EBOOT with "
            "Utilities > Decrypt PS3 Binaries and pick the .elf instead."
        )
    directory = Path(tempfile.mkdtemp(prefix="spartacus-eboot-"))
    copy = directory / "EBOOT.BIN"
    copy.write_bytes(eboot_path.read_bytes())
    try:
        try:
            with preserved_run_files(rpcs3_exe.parent, directory / "saved"), \
                    outside_program_dll_search():
                completed = subprocess.run(
                    [str(rpcs3_exe), "--decrypt", str(copy)],
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env=rpcs3_environment(),
                    cwd=str(rpcs3_exe.parent),
                )
        except subprocess.TimeoutExpired as error:
            raise EbootSourceError(
                f"rpcs3.exe --decrypt did not finish within {timeout:g} "
                "seconds. Close RPCS3 and try again, or use Utilities > "
                "Decrypt PS3 Binaries and pick the .elf."
            ) from error
        except OSError as error:
            raise EbootSourceError(
                f"could not run rpcs3.exe --decrypt: {error}"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or b"").decode("mbcs", "replace").strip()
            raise EbootSourceError(
                "rpcs3.exe --decrypt failed with exit code "
                f"{completed.returncode}"
                + (f": {detail}" if detail else "")
                + ". Use Utilities > Decrypt PS3 Binaries and pick the .elf "
                "instead."
            )
        elf_path = find_decrypted_elf(directory)
        if elf_path is None:
            raise EbootSourceError(
                "RPCS3 could not decrypt the executable on its own (some "
                "RPCS3 versions stop with an error window when started only "
                "to decrypt; that window is harmless - just close it). In "
                "RPCS3, use Utilities > Decrypt PS3 Binaries on the game's "
                "EBOOT.BIN, then choose the produced .elf here instead."
            )
        return elf_path.read_bytes(), directory
    except BaseException:
        _remove_tree(directory)
        raise


@contextmanager
def preserved_run_files(rpcs3_root: Path, store: Path):
    """Save RPCS3's log files, run the body, then restore them exactly.

    Files that did not exist before are left as RPCS3 wrote them; a file
    that cannot be restored is reported rather than silently lost.
    """
    saved: list[tuple[Path, Path]] = []
    for relative in RPCS3_RUN_FILES:
        original = Path(rpcs3_root) / relative
        if original.is_file():
            backup = Path(store) / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(original, backup)
            except PermissionError:
                # A running RPCS3 holds its log open exclusively. It cannot
                # be read, and for the same reason the decrypt run cannot
                # rewrite it, so there is nothing to preserve.
                continue
            saved.append((original, backup))
    try:
        yield
    finally:
        pending = list(saved)
        failures: list[str] = []
        for attempt in range(RESTORE_ATTEMPTS):
            failures = []
            remaining = []
            for original, backup in pending:
                try:
                    shutil.copy2(backup, original)
                except OSError as error:
                    remaining.append((original, backup))
                    failures.append(f"{original}: {error}")
            pending = remaining
            if not pending:
                break
            time.sleep(RESTORE_DELAY)
        if pending:
            # Never lose the user's log: keep each copy right beside the
            # original (it outlives the caller's temporary directory, and
            # is where a user looks), and say where.
            kept = []
            for original, backup in pending:
                beside = original.with_name(original.name + ".before-decrypt")
                try:
                    shutil.copy2(backup, beside)
                    kept.append(str(beside))
                except OSError as error:
                    failures.append(f"{beside}: {error}")
            raise EbootSourceError(
                "RPCS3 was still holding its log after decrypting, so it "
                "could not be put back. Your previous log is saved as "
                + (", ".join(kept) or "nothing (saving it failed too)")
                + ". Details: " + "; ".join(failures))


def _remove_tree(directory: Path) -> None:
    import shutil

    try:
        shutil.rmtree(directory)
    except OSError:
        pass


@contextmanager
def open_eboot(eboot_path: Path, rpcs3_folder: Path | None = None,
               allow_decrypt: bool = False, timeout: float = DECRYPT_TIMEOUT):
    """Yield the decrypted ELF bytes for ``eboot_path``.

    ``allow_decrypt`` is the explicit user opt-in for running RPCS3's
    ``--decrypt``. Without it a non-ELF file only produces the Utilities
    message; nothing is executed.
    """
    path = Path(eboot_path)
    if not path.is_file():
        raise EbootSourceError(f"EBOOT file not found: {path}")
    if is_elf(path):
        yield path.read_bytes()
        return
    if not allow_decrypt:
        raise EbootSourceError(UTILITIES_MESSAGE)
    if rpcs3_folder is None:
        raise EbootSourceError(
            "RPCS3 decryption needs the RPCS3 folder (the one containing "
            "rpcs3.exe), or decrypt the EBOOT with Utilities > Decrypt PS3 "
            "Binaries and pick the .elf instead."
        )
    elf_bytes, directory = decrypt_with_rpcs3(path, rpcs3_folder, timeout)
    try:
        yield elf_bytes
    finally:
        _remove_tree(directory)
