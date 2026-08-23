"""
Language Registry

Phase 4. One place that knows which languages exist, which file extensions
belong to them, and whether each is usable on this machine.

Adapters register themselves here at import time. ``detect_language`` is
the only lookup the commands need: everything else — dispatching to the
native Python engine or to the generic pipeline — happens in
:mod:`algorithms.abstract_source`.
"""

from pathlib import Path
from typing import Optional

from core.languages.base import (  # noqa: F401 - re-exported
    AdapterInfo,
    Edit,
    LanguageAdapter,
    SourceSymbol,
    adapter_info,
    apply_edits,
    get_adapter,
    identity_line_map,
    language_for_extension,
    register,
    registered_languages,
)
from core.languages.javascript import JavaScriptAdapter
from core.languages.python_adapter import PythonAdapter

register(PythonAdapter())
register(JavaScriptAdapter())


def detect_language(path) -> Optional[str]:
    """
    Identify a file's language from its extension.

    Args:
        path: File path.

    Returns:
        A registered language name, or None if the extension is unknown.
        None rather than a guess: abstracting a file with the wrong parser
        would either fail loudly or, worse, quietly abstract nothing.
    """
    return language_for_extension(Path(path).suffix)


def adapter_for_path(path):
    """
    Return an adapter configured for *path*.

    JavaScript and TypeScript share an adapter class but need different
    grammars, so the extension is passed through rather than dropped.
    """
    language = detect_language(path)
    if language is None:
        raise KeyError(f"no adapter for {Path(path).suffix or 'this file type'}")

    if language == 'javascript':
        return JavaScriptAdapter(
            dialect=JavaScriptAdapter.dialect_for(Path(path).suffix)
        )
    return get_adapter(language)
