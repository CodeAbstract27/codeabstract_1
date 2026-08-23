"""
Language-Agnostic Node Interface

Phase 4 — the refactor the "second language" workstream is gated on.

Everything before this phase was written against :mod:`ast`. That is not a
criticism of it — a Python tool should use the Python parser — but it left
the project unable to answer the question its own proposal raises: is
bidirectional abstraction a general technique, or a Python ``ast`` trick?

The interface here is deliberately thin. It does **not** try to model a
universal AST; every attempt at one ends up either Python-shaped or too
abstract to classify against. What it models instead is the only thing the
engine actually needs from a parse tree:

    *a list of named things, each with a byte range, a kind, and a scope*

That is enough to classify, tokenise, and rewrite, and it is the same for
Python, JavaScript, Go or Rust. Everything language-specific — how a
declaration is spelled, which names are globals, what counts as a module
import — stays inside the adapter.

Rewriting by **byte range** rather than by mutating and re-printing a tree
has a property worth stating: the output is the input with names swapped,
so formatting, comments and line numbers all survive unchanged. The Python
path cannot do this (``ast.unparse`` reprints the file, which is why Phase 1
needed a line index at all); adapters built on this interface get an
identity line map for free.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

# Kinds a symbol can have. These map onto token prefixes and are chosen to
# be spellable in any language, not to mirror one language's node names.
KIND_FUNCTION = 'function'
KIND_CLASS = 'class'
KIND_VARIABLE = 'variable'
KIND_PARAMETER = 'parameter'
KIND_PROPERTY = 'property'
KIND_MODULE = 'module'
KIND_STRING = 'string'
KIND_NUMBER = 'number'


@dataclass
class SourceSymbol:
    """
    One named thing in a source file, located by byte range.

    Args:
        name: The identifier or literal text as written.
        kind: One of the ``KIND_*`` constants.
        start_byte: Inclusive start offset of the text to replace.
        end_byte: Exclusive end offset.
        lineno: 1-based line of this occurrence.
        col: 0-based column.
        scope: Dotted path of enclosing functions/classes, for symbol
            identity. Two ``result`` variables in different functions are
            different symbols.
        is_binding: True where the name is declared rather than used. The
            declaration site is what the privacy report cites.
        is_literal: True for string and number literals.
        is_numeric: True for numeric literals.
        inherited: ``'SECRET'`` when the binding context marks this symbol,
            e.g. the string assigned to ``apiKey``.
        namespace: Overrides lexical scoping for symbol identity. A member
            name is reached as ``obj.field`` from anywhere, so it belongs
            to a ``'property'`` namespace rather than to the function it
            happens to appear in; a module binding belongs to ``'module'``
            for the same reason. Without this, one name picked up two
            tokens at two sites and the emitted file stopped being valid
            code.
    """

    name: str
    kind: str
    start_byte: int
    end_byte: int
    lineno: int
    col: int = 0
    scope: str = 'module'
    is_binding: bool = False
    is_literal: bool = False
    is_numeric: bool = False
    inherited: Optional[str] = None
    namespace: Optional[str] = None

    @property
    def symbol_key(self) -> Tuple[str, str, str]:
        """
        Identity for token reuse: same key → same token.

        Three namespaces, mirroring what Phase 1 / D4 established for
        Python. Literals key on their own text, so one string constant used
        twice gets one token. Symbols with an explicit *namespace* key
        globally within it, because that is how they are reached. Everything
        else keys on lexical scope, so two ``result`` variables in two
        functions stay distinct rather than collapsing into one.
        """
        if self.is_literal:
            return ('literal', '', self.name)
        if self.namespace:
            return (self.namespace, '', self.name)
        return ('name', self.scope, self.name)

    @property
    def signal_text(self) -> str:
        """Text handed to the classifier's name-pattern tier."""
        return self.name


class LanguageAdapter(Protocol):
    """
    What a language must provide to be abstracted.

    Three methods, because three is what the driver in
    :mod:`algorithms.abstract_source` calls.
    """

    language: str
    extensions: Tuple[str, ...]

    def availability(self) -> Tuple[bool, str]:
        """``(usable, reason)`` — reason explains what is missing if not."""
        ...

    def symbols(self, source_code: str) -> List[SourceSymbol]:
        """Extract every abstractable symbol, in source order."""
        ...

    def is_builtin(self, name: str) -> bool:
        """True for language globals that must keep their names."""
        ...


@dataclass
class AdapterInfo:
    """A registry entry, including why an adapter may be unusable."""

    language: str
    extensions: Sequence[str]
    available: bool
    reason: str = ""


# ═══════════════════════════════════════════════════════════
# Shared rewriting
# ═══════════════════════════════════════════════════════════

@dataclass
class Edit:
    """A byte-range replacement."""

    start_byte: int
    end_byte: int
    replacement: str


def apply_edits(source_code: str, edits: List[Edit]) -> str:
    """
    Apply replacements to *source_code*.

    Edits are applied last-to-first so that earlier offsets stay valid, and
    overlapping edits are dropped rather than merged — an overlap means two
    symbols claim the same bytes, and silently letting one win would emit
    code that no longer means what it did.

    Args:
        source_code: The original text.
        edits: Replacements, in any order.

    Returns:
        The rewritten text.

    Note:
        This is the collision-safety argument from Phase 0 / D2 in a
        stronger form. There, ``VAR_1`` could match inside ``VAR_10``
        because substitution was by pattern; here a symbol is identified by
        its byte range, so a replacement cannot match anything at all.
    """
    if not edits:
        return source_code

    data = source_code.encode('utf-8')
    ordered = sorted(edits, key=lambda e: e.start_byte, reverse=True)

    last_start = len(data) + 1
    out = data
    for edit in ordered:
        if edit.end_byte > last_start:
            continue  # overlaps an edit already applied
        out = out[:edit.start_byte] + edit.replacement.encode('utf-8') + out[edit.end_byte:]
        last_start = edit.start_byte

    return out.decode('utf-8')


def identity_line_map(source_code: str) -> Dict[int, int]:
    """
    Line index for adapters that rewrite in place.

    Byte-range substitution never adds or removes a line, so abstract line
    *n* is original line *n*. Returned explicitly rather than left empty:
    an empty index means "no translation available" to RECONSTRUCT, which
    would leave citations untranslated on the assumption they might be
    wrong, when here they are known to be right.
    """
    total = len(source_code.splitlines()) or 1
    return {n: n for n in range(1, total + 1)}


# ═══════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════

_ADAPTERS: Dict[str, Any] = {}
_EXTENSIONS: Dict[str, str] = {}


def register(adapter) -> None:
    """Add an adapter to the registry, keyed by language and extension."""
    _ADAPTERS[adapter.language] = adapter
    for extension in adapter.extensions:
        _EXTENSIONS[extension] = adapter.language


def get_adapter(language: str):
    """
    Look up an adapter by language name.

    Raises:
        KeyError: If the language is not registered.
    """
    return _ADAPTERS[language]


def registered_languages() -> List[str]:
    """Every registered language name."""
    return sorted(_ADAPTERS)


def language_for_extension(extension: str) -> Optional[str]:
    """Map a file extension (with the dot) to a language name."""
    return _EXTENSIONS.get(extension.lower())


def adapter_info() -> List[AdapterInfo]:
    """Registry contents with availability, for ``codeabstract languages``."""
    infos = []
    for name in registered_languages():
        adapter = _ADAPTERS[name]
        available, reason = adapter.availability()
        infos.append(AdapterInfo(
            language=name,
            extensions=list(adapter.extensions),
            available=available,
            reason=reason,
        ))
    return infos
