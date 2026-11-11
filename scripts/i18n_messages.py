#!/usr/bin/env python3
"""List the translatable English messages and check the catalogues.

Every literal passed to ``tr()``, ``N_()`` or as the text of ``tr_in()`` in
``tools/`` is a message. Run with no arguments to report messages a catalogue
lacks, entries no code uses any more, and placeholder mismatches; exits 1 if
there is any problem.

    python scripts/i18n_messages.py          # check
    python scripts/i18n_messages.py --list   # print every message
"""

from __future__ import annotations

import ast
from pathlib import Path
import string
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

MARKERS = {"tr": 0, "N_": 0, "tr_in": 1}


def _name(func) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def messages(root: Path = TOOLS) -> dict[str, list[str]]:
    """English message -> where it is used (``file:line``)."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if "translations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            index = MARKERS.get(_name(node.func))
            if index is None or len(node.args) <= index:
                continue
            argument = node.args[index]
            if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str):
                where = f"{path.relative_to(ROOT)}:{node.lineno}"
                found.setdefault(argument.value, []).append(where)
    return found


def placeholders(text: str) -> set[str]:
    return {field for _literal, field, _spec, _conv
            in string.Formatter().parse(text) if field is not None}


def problems() -> list[str]:
    import i18n
    found = messages()
    report = []
    for code, catalogue in i18n.CATALOGUES.items():
        for text in sorted(set(found) - set(catalogue)):
            report.append(f"{code}: missing {text!r} ({found[text][0]})")
        for text in sorted(set(catalogue) - set(found)):
            report.append(f"{code}: unused {text!r}")
        for text, translated in catalogue.items():
            if text in found and placeholders(text) != placeholders(
                    translated):
                report.append(f"{code}: placeholders differ for {text!r}")
    return report


def main(argv) -> int:
    if "--list" in argv:
        for text in sorted(messages()):
            print(repr(text))
        return 0
    report = problems()
    for line in report:
        print(line)
    print(f"{len(messages())} messages, {len(report)} problems")
    return 1 if report else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
