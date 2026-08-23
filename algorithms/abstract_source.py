"""
Language-Agnostic ABSTRACT Driver

Phase 4. ABSTRACT(S, k) for any language with an adapter.

This is the same algorithm as :func:`algorithms.abstract.abstract` —
classify, tokenise, replace, encrypt — expressed over
:class:`core.languages.base.SourceSymbol` instead of over Python AST nodes.
Python itself is *not* routed through here: :func:`abstract_source` hands
it to the native engine, which knows more about Python than this interface
can express (see :mod:`core.languages.python_adapter`).

The two paths share what matters. Both call
:func:`algorithms.classify.classify_signals`, so a credential is judged by
the same tiers with the same confidences whatever language it sits in; both
produce the same :class:`~algorithms.abstract.AbstractionResult`, so
RECONSTRUCT, the privacy report, the session store and the audit log work
on a JavaScript session with no branching at all.

One structural difference is worth stating because it is an improvement,
not a compromise: replacement here is by **byte range**, so the output is
the input with names swapped. Formatting survives and the line map is the
identity rather than a reconstruction — see
:func:`core.languages.base.apply_edits`.

That same property is why comments need explicit handling here. Python's
comments disappear because ``ast.unparse`` cannot reproduce them; nothing
in a byte-range rewrite removes anything it was not told to, so a key in a
``//`` comment travelled at every privacy level until :func:`_screen_comments`
applied the policy that :mod:`core.comment_handler` had already stated.
"""

import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from algorithms.abstract import (
    AbstractionResult,
    _finalise_kept,
    _record_kept,
    _should_abstract,
)
from algorithms.classify import classify_signals
from algorithms.encrypt import encrypt_mapping
from config.ignore_rules import OverrideRules
from config.settings import PRIVACY_LEVELS
from core.context_extractor import get_context
from core.languages import adapter_for_path, detect_language, get_adapter
from core.languages.base import (
    KIND_CLASS,
    KIND_FUNCTION,
    KIND_MODULE,
    KIND_NUMBER,
    KIND_STRING,
    Edit,
    SourceSymbol,
    apply_edits,
    identity_line_map,
)
from core.token_generator import TokenGenerator

# Symbol kind → token prefix. Deliberately the same vocabulary
# ``algorithms.helpers.label_to_prefix`` produces, so RECONSTRUCT's token
# pattern needs no new cases and a JavaScript session's tokens read exactly
# like a Python one's.
_KIND_PREFIX = {
    KIND_FUNCTION: 'FUNC',
    KIND_CLASS: 'CLASS',
    KIND_MODULE: 'MODULE',
    KIND_STRING: 'CONST',
    KIND_NUMBER: 'NUM',
}


def prefix_for(symbol: SourceSymbol, label: str) -> str:
    """Token prefix for a classified symbol."""
    if label == 'SECRET':
        return 'SECRET'
    return _KIND_PREFIX.get(symbol.kind, 'VAR')


def _is_significant(
    symbol: SourceSymbol,
    adapter,
    privacy_level: str,
) -> bool:
    """
    The adapter-side equivalent of ``IsSemanticallySig(E)``.

    Same three rules as the Python helper: language globals keep their
    names, single-character identifiers survive below ``critical``, and
    dunder-style names are structural rather than proprietary.
    """
    if not symbol.name:
        return False

    if not symbol.is_literal and adapter.is_builtin(symbol.name):
        return False

    level = PRIVACY_LEVELS.get(privacy_level, PRIVACY_LEVELS['medium'])
    if not level.get('abstract_short_names', False):
        if len(symbol.name) <= 1 and not symbol.is_literal:
            return False

    if symbol.name.startswith('__') and symbol.name.endswith('__'):
        return False

    return True


def abstract_source(
    source_code: str,
    language: str = "python",
    context_window: int = 3,
    privacy_level: str = "high",
    overrides: Optional[OverrideRules] = None,
    keep_comments: bool = False,
    adapter=None,
) -> AbstractionResult:
    """
    ABSTRACT(S, k) for *language*.

    Args:
        source_code: The source file's text.
        language: Registered language name. ``python`` is delegated to
            :func:`algorithms.abstract.abstract`.
        context_window: Context window size k.
        privacy_level: ``low`` | ``medium`` | ``high`` | ``critical``.
        overrides: Project rules from ``.codeabstractignore``.
        keep_comments: Re-inject screened comments instead of stripping
            them. Honoured by every adapter that implements ``comments()``:
            rewriting in place means comments are never removed as a side
            effect the way ``ast.unparse`` removes them, so the policy in
            :mod:`core.comment_handler` has to be applied deliberately —
            see :func:`_screen_comments`.
        adapter: Explicit adapter, mainly for the TypeScript grammar.

    Returns:
        An :class:`~algorithms.abstract.AbstractionResult`, identical in
        shape to the Python engine's.

    Raises:
        ValueError: If the source does not parse.
        KeyError: If the language has no adapter.
        core.languages.javascript.LanguageUnavailable: If the adapter's
            parser is not installed.
    """
    if language == 'python':
        from algorithms.abstract import abstract
        return abstract(
            source_code=source_code,
            context_window=context_window,
            privacy_level=privacy_level,
            overrides=overrides,
            keep_comments=keep_comments,
        )

    adapter = adapter or get_adapter(language)
    rules = overrides if overrides is not None else OverrideRules()

    symbols = adapter.symbols(source_code)

    mapping_table: Dict[str, Dict] = {}
    seen: Dict[tuple, str] = {}
    occurrences: Dict[str, List[Dict]] = {}
    definition_lines: Dict[str, int] = {}
    kept: Dict[tuple, Dict] = {}
    edits: List[Edit] = []

    token_gen = TokenGenerator({
        'FUNC': 0, 'VAR': 0, 'SECRET': 0, 'CONST': 0,
        'CLASS': 0, 'NUM': 0, 'MODULE': 0,
    })

    stats = {
        'total_nodes': len(symbols),
        'abstracted_nodes': 0,
        'skipped_nodes': 0,
        'secrets_found': 0,
        'values_found': 0,
        'modules_abstracted': 0,
        'modules_preserved': 0,
        'overrides_applied': 0,
        'low_confidence_nodes': 0,
    }

    # A symbol tokenised anywhere must be tokenised everywhere: leaving one
    # occurrence readable would both leak the name and emit code that no
    # longer refers to the same thing.  Modules are the common case —
    # ``import { ledger }`` is abstracted, so every ``ledger`` must be.
    forced_keys: Set[tuple] = {
        symbol.symbol_key for symbol in symbols if symbol.kind == KIND_MODULE
    }

    for symbol in symbols:
        if not _is_significant(symbol, adapter, privacy_level):
            stats['skipped_nodes'] += 1
            continue

        # ── Classify ──────────────────────────────────
        if rules.is_forced_secret(symbol.name):
            from algorithms.classify import Decision
            decision = Decision(
                label='SECRET', confidence=1.0, detector='override',
                evidence=['forced by .codeabstractignore'],
            )
            stats['overrides_applied'] += 1
        else:
            decision = classify_signals(
                text=symbol.signal_text,
                literal=symbol.name if symbol.is_literal and not symbol.is_numeric else "",
                is_numeric_literal=symbol.is_numeric,
                inherited=symbol.inherited,
            )

        label = decision.label
        if decision.needs_review:
            stats['low_confidence_nodes'] += 1

        # A keep rule recovers utility but cannot rescue a real secret —
        # the Phase 1 rule, unchanged.
        if label != 'SECRET' and rules.should_keep(symbol.name):
            stats['overrides_applied'] += 1
            stats['skipped_nodes'] += 1
            _record_kept(kept, symbol.name, 'keep rule', symbol.lineno, label)
            continue

        forced = symbol.symbol_key in forced_keys
        if not forced and not _should_abstract(label, privacy_level):
            stats['skipped_nodes'] += 1
            _record_kept(
                kept, symbol.name, f"privacy level '{privacy_level}'",
                symbol.lineno, label,
            )
            continue

        if label == 'SECRET':
            stats['secrets_found'] += 1
        elif label == 'VALUE':
            stats['values_found'] += 1

        # ── Tokenise ──────────────────────────────────
        key = symbol.symbol_key
        if key in seen:
            token = seen[key]
        else:
            token = token_gen.generate(prefix_for(symbol, label))
            mapping_table[token] = {
                'name': symbol.name,
                'label': label,
                'node_type': symbol.kind,
                'lineno': symbol.lineno,
                'ctx': get_context(source_code, symbol.lineno, context_window),
                'scope': symbol.scope,
                'confidence': decision.confidence,
                'detector': decision.detector,
                'evidence': decision.evidence,
            }
            seen[key] = token
            if symbol.kind == KIND_MODULE:
                stats['modules_abstracted'] += 1

        occurrences.setdefault(token, []).append({
            'lineno': symbol.lineno,
            'col': symbol.col,
        })
        if symbol.is_binding and token not in definition_lines:
            definition_lines[token] = symbol.lineno

        edits.append(Edit(symbol.start_byte, symbol.end_byte, token))
        stats['abstracted_nodes'] += 1

    # ── Prefer the binding site as the definition line ────
    for token, entry in mapping_table.items():
        entry_occurrences = occurrences.get(token, [])
        entry['occurrences'] = entry_occurrences

        definition_line = definition_lines.get(token)
        if definition_line is None and entry_occurrences:
            definition_line = min(o['lineno'] for o in entry_occurrences)

        if definition_line is not None and definition_line != entry['lineno']:
            entry['lineno'] = definition_line
            entry['ctx'] = get_context(source_code, definition_line, context_window)

    stats['unique_symbols'] = len(mapping_table)

    # ── Comments ──────────────────────────────────────────
    # The adapter rewrites in place, so comments survive unless something
    # removes them — and nothing did, which made a key in a ``//`` comment
    # a leak path at every privacy level, ``critical`` included. The policy
    # is stated once, in ``core.comment_handler``, and applies to every
    # language: stripped by default, screened when kept.
    comment_edits, comments_kept = _screen_comments(
        source_code, adapter, seen, mapping_table, keep_comments,
    )
    edits.extend(comment_edits)
    stats['comments_kept'] = comments_kept

    abstract_code = apply_edits(source_code, edits)
    encrypted_mapping, encryption_key = encrypt_mapping(mapping_table)

    return AbstractionResult(
        abstract_code=abstract_code,
        encrypted_mapping=encrypted_mapping,
        encryption_key=encryption_key,
        session_id=str(uuid.uuid4()),
        statistics=stats,
        line_map=identity_line_map(source_code),
        kept=_finalise_kept(kept),
        language=language,
    )


def _screen_comments(
    source_code: str,
    adapter,
    seen: Dict[tuple, str],
    mapping_table: Dict[str, Dict],
    keep_comments: bool,
) -> Tuple[List[Edit], int]:
    """
    Apply the project's comment policy to a non-Python file.

    The policy lives in :mod:`core.comment_handler` and is not
    Python-specific: a comment is free-form prose written by the people who
    own the code, and it is where business context lives most densely, so it
    is stripped by default and preservation is opt-in. The engine that
    enforces it for Python is ``ast.unparse``, which drops comments as a
    side effect; an adapter that rewrites bytes in place has no equivalent,
    so it has to be done deliberately.

    When *keep_comments* is set, surviving comments are screened exactly as
    Python's are: any comment whose text trips the secret or business-value
    classifier is dropped, and identifiers inside the survivors are
    rewritten to their tokens, so prose cannot leak a name the code took
    care to hide.

    Args:
        source_code: The original text.
        adapter: The language adapter; must expose ``comments()``.
        seen: ``symbol_key`` → token, for identifier rewriting.
        mapping_table: Token → entry, for the original names.
        keep_comments: False strips every comment; True screens them.

    Returns:
        ``(edits, comments_kept)``.
    """
    from core.comment_handler import is_sensitive_comment, rewrite_identifiers

    reader = getattr(adapter, 'comments', None)
    if reader is None:
        # An adapter with no comment support cannot be screened, and
        # claiming otherwise in the statistics would be worse than saying
        # nothing. Its files keep their comments; this is the reason a new
        # adapter should implement the method.
        return [], 0

    comments = reader(source_code)
    if not comments:
        return [], 0

    name_to_token = {
        entry['name']: token
        for token, entry in mapping_table.items()
        if isinstance(entry.get('name'), str)
    }

    edits: List[Edit] = []
    kept_count = 0

    for start_byte, end_byte, text in comments:
        if not keep_comments or is_sensitive_comment(text):
            edits.append(Edit(start_byte, end_byte, ''))
            continue

        rewritten = rewrite_identifiers(text, name_to_token)
        kept_count += 1
        if rewritten != text:
            edits.append(Edit(start_byte, end_byte, rewritten))

    return edits, kept_count


def abstract_file(
    path,
    source_code: Optional[str] = None,
    context_window: int = 3,
    privacy_level: str = "high",
    overrides: Optional[OverrideRules] = None,
    keep_comments: bool = False,
) -> AbstractionResult:
    """
    Abstract a file, choosing the engine from its extension.

    Args:
        path: Path to the source file, used to pick the language.
        source_code: File contents; read from *path* if omitted.
        context_window: Context window size k.
        privacy_level: Privacy level.
        overrides: Project rules from ``.codeabstractignore``.
        keep_comments: Python only — see :func:`abstract_source`.

    Returns:
        An :class:`~algorithms.abstract.AbstractionResult`.

    Raises:
        ValueError: If the extension maps to no known language. Guessing
            Python for an unknown extension would abstract a file with the
            wrong parser, and the failure mode of that is a file that looks
            abstracted and is not.
    """
    file_path = Path(path)
    language = detect_language(file_path)
    if language is None:
        from core.languages import registered_languages
        raise ValueError(
            f"No language adapter for '{file_path.suffix or file_path.name}'. "
            f"Supported: {', '.join(registered_languages())}"
        )

    if source_code is None:
        source_code = file_path.read_text(encoding='utf-8')

    return abstract_source(
        source_code=source_code,
        language=language,
        context_window=context_window,
        privacy_level=privacy_level,
        overrides=overrides,
        keep_comments=keep_comments,
        adapter=None if language == 'python' else adapter_for_path(file_path),
    )
