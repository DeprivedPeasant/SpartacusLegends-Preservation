#!/usr/bin/env python3
"""Interface language for the messages a player reads.

English text is the key: ``tr("Server ready")`` returns the catalogue entry for
the current language, or the English text itself when there is none. Text with
values uses named placeholders, ``tr("Logged in as {name}", name=user)``, so a
translation can put them where its grammar needs them.

Constants defined at import time are marked with :func:`N_` and translated
where they are shown, because the language is chosen after import.

The language lives in the ``SPARTACUS_LANGUAGE`` environment variable rather
than in module state: the frozen apps import these modules both as ``x`` and
as ``tools.x``, and the server the GUI starts inherits the variable, so every
copy agrees. Unset means English, which keeps the log files and the console
tools English unless a language is chosen.

No Qt and no third-party imports: the console server must keep working on a
bare Python install.
"""

from __future__ import annotations

import locale
import os

try:
    from translations import es, pt_BR
except ImportError:  # Imported as tools.i18n by the unit tests.
    from tools.translations import es, pt_BR


ENV_VAR = "SPARTACUS_LANGUAGE"
ENGLISH = "en"

# Code -> name shown in the language menu, each in its own language.
LANGUAGES = {
    "en": "English",
    "es": "Español",
    "pt_BR": "Português (Brasil)",
}

CATALOGUES = {
    "es": es.MESSAGES,
    "pt_BR": pt_BR.MESSAGES,
}


def N_(text: str) -> str:
    """Mark a constant for translation; it is translated where it is shown."""
    return text


def normalise(code) -> str | None:
    """Map a locale name such as ``es-MX`` or ``pt_PT`` to a supported code."""
    if not code:
        return None
    text = str(code).strip().replace("-", "_").split(".")[0]
    language = text.split("_")[0].lower()
    if language == "en":
        return "en"
    if language == "es":
        return "es"
    if language == "pt":
        # Only Brazilian Portuguese is written; it reads fine in Portugal.
        return "pt_BR"
    return None


def language_from(names) -> str:
    """The first supported language among locale names, else English."""
    for name in names:
        code = normalise(name)
        if code is not None:
            return code
    return ENGLISH


def system_locale_names() -> list[str]:
    """The user's interface language names, most preferred first."""
    names: list[str] = []
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            buffer = ctypes.create_unicode_buffer(85)
            language_id = kernel32.GetUserDefaultUILanguage()
            if kernel32.LCIDToLocaleName(language_id, buffer, len(buffer), 0):
                names.append(buffer.value)
            if kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                names.append(buffer.value)
        except (AttributeError, OSError, ValueError):
            pass
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(variable):
            names.append(os.environ[variable])
    try:
        current = locale.getlocale()[0]
    except ValueError:
        current = None
    if current:
        names.append(current)
    return names


def current() -> str:
    return normalise(os.environ.get(ENV_VAR)) or ENGLISH


def set_language(code: str) -> str:
    """Use ``code`` (or English if unsupported) here and in child processes."""
    chosen = normalise(code) or ENGLISH
    os.environ[ENV_VAR] = chosen
    return chosen


def use_system_language_if_unset() -> str:
    """For the console programs: follow Windows unless a language was set."""
    if normalise(os.environ.get(ENV_VAR)) is None:
        return set_language(language_from(system_locale_names()))
    return current()


def tr_in(code: str, text: str, /, **values) -> str:
    """``tr`` for one other language, without switching to it."""
    before = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = normalise(code) or ENGLISH
    try:
        return tr(text, **values)
    finally:
        if before is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = before


def tr(text: str, /, **values) -> str:
    """``text`` in the current language, with ``values`` filled in."""
    catalogue = CATALOGUES.get(current())
    translated = catalogue.get(text, text) if catalogue else text
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):
        # A broken translation must never hide the message itself.
        return text.format(**values)
