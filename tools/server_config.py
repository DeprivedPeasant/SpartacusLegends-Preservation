"""Shared persisted configuration for the installer and server launcher."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from i18n import N_
except ImportError:  # Imported as tools.server_config by the unit tests.
    from tools.i18n import N_


CONFIG_RELATIVE_PATH = Path("data") / "server-config.json"
DEFAULT_TITLE_VERSION = "01.00"
SUPPORTED_TITLE_VERSIONS = ("01.00", "01.06")
TITLE_VERSION_UNKNOWN_MESSAGE = N_(
    "The game version is not set and your saves do not show which one you "
    "have. Run Patch setup in SpartacusLegendsServerGUI.exe, or "
    "SpartacusLegendsPatchInstaller.exe, or start the server with "
    "--title-version 01.00 or --title-version 01.06. The server does not "
    "guess: the wrong version puts saves in the wrong folder."
)


class TitleVersionUnknownError(ValueError):
    """Nothing says which build the player has, so the server must not start."""


def config_path(base_dir: Path) -> Path:
    return Path(base_dir) / CONFIG_RELATIVE_PATH


def encode_title_version(title_version: str) -> str:
    if title_version not in SUPPORTED_TITLE_VERSIONS:
        raise ValueError(f"unsupported title version {title_version!r}")
    return json.dumps(
        {"title_version": title_version}, indent=2, sort_keys=True
    ) + "\n"


def read_title_version(path: Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"could not read server configuration {path}: {error}") \
            from error
    title_version = document.get("title_version") \
        if isinstance(document, dict) else None
    if title_version not in SUPPORTED_TITLE_VERSIONS:
        raise ValueError(
            f"server configuration {path} has unsupported title_version "
            f"{title_version!r}; expected one of "
            f"{', '.join(SUPPORTED_TITLE_VERSIONS)}"
        )
    return title_version
