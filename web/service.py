"""
Web Service Layer — the pipeline, with no Flask in it.

Phase 5. The web interface is the proposal's Option B, and the proposal
lists five output formats for it: the abstracted code, the local vault, the
raw LLM analysis, the mapped feedback, and the privacy report. All five are
produced here; :mod:`web.routes` only decides which of them a given HTTP
request gets back.

Keeping the pipeline out of the request handlers is not tidiness. Two of
the guarantees this project makes are properties of *what leaves the
machine*, and they are far easier to test on a function that returns a
dataclass than on a rendered page — see ``tests/test_web/``.

Three rules hold everywhere in this module:

* **The browser is not the terminal.** A rendered page persists in history,
  is visible to extensions and devtools, and is what gets screen-shared in
  a demo. Secret *values* are therefore masked in every structure that
  crosses back to the client, including the reconstructed feedback and the
  source-context blocks inside it. ``reveal=True`` opts out, exactly as
  ``--reveal`` does for the CLI's privacy report.
* **No path ever comes from the client.** The CLI takes a filename and
  reads it; a web server that did the same would read any file the server
  process can see. What arrives here is *content* plus a name used only to
  pick a language adapter, and that name is reduced to a basename before
  anything looks at it.
* **The vault stays local.** The mapping table is what the abstraction
  exists to keep back. It is shown, masked, in its own panel — labelled as
  never-sent — and it is never part of a provider payload.

One boundary is worth stating exactly, because a loose version of it would
be false. The original-code pane echoes the submitted source back verbatim,
credentials included, and that is not a leak: the browser is where the
source came from, and the side-by-side view the proposal asks for cannot
exist without it. The claim that *is* made, and that
``tests/test_web/test_web_privacy.py`` asserts, is narrower and checkable —
**no secret value appears in anything derived from the source**: not the
abstract code, not the vault, not the privacy report, not the reconstructed
feedback, and not the provider payload.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from algorithms.abstract_source import abstract_file
from algorithms.encrypt import decrypt_mapping, encrypt_mapping
from algorithms.reconstruct import reconstruct
from config.settings import PRIVACY_LEVELS
from core.languages import adapter_info, detect_language
from core.privacy_report import build_report
# display_mapping / mask_mapping_table moved to core.privacy_report (see
# the "Masking" section below) but stay re-exported here, unused in this
# module's own code, because tests and other callers reach them as
# service.display_mapping / service.mask_mapping_table.
from core.privacy_report import display_mapping  # noqa: F401
from core.privacy_report import mask_mapping_table  # noqa: F401
from core.query_abstractor import abstract_query
from llm import ProviderError, create_client, provider_status
from llm.base import TASK_PROMPTS, build_prompt
from storage import audit_log
from storage.session_manager import (
    delete_session,
    list_sessions,
    load_session,
    save_session,
)

# ═══════════════════════════════════════════════════════════
# Limits
# ═══════════════════════════════════════════════════════════

# A browser can paste an arbitrarily large buffer, and abstraction is
# CPU-bound: the AST walk, the scope tree and the line-map pairing all scale
# with the file. 512 KiB is well above the largest file in the project's own
# corpus and still returns inside a request timeout.
MAX_SOURCE_BYTES = 512 * 1024

# k beyond this stops being "context" and starts being "most of the file,
# repeated once per token", which makes the response quadratic in the
# mapping size for no readable benefit.
MAX_CONTEXT_WINDOW = 20

MAX_QUERY_CHARS = 2000

# Tokens as ABSTRACT emits them.  Kept in step with
# ``algorithms.reconstruct._extract_tokens`` -- if a prefix is added there
# and not here, the abstract-code panel silently stops highlighting it.
TOKEN_PATTERN = re.compile(
    r'\b((?:FUNC|VAR|SECRET|CONST|NUM|CLASS|MODULE)_\d+)\b'
)


class WebServiceError(Exception):
    """
    A request that cannot be served, with the status the route should use.

    Carrying the status here keeps the routes free of a second layer of
    validation that could disagree with this one.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ═══════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════

def validate_privacy(level: Optional[str]) -> str:
    """Check a privacy level, naming the alternatives when it is wrong."""
    value = (level or 'high').strip().lower()
    if value not in PRIVACY_LEVELS:
        raise WebServiceError(
            f"Unknown privacy level '{level}'. "
            f"Choose one of: {', '.join(PRIVACY_LEVELS)}"
        )
    return value


def validate_context_window(value: Any) -> int:
    """Coerce and bound the context window k."""
    if value is None or value == '':
        return 3
    try:
        window = int(value)
    except (TypeError, ValueError):
        raise WebServiceError(
            f"Context window must be a whole number, got {value!r}"
        )
    if not 0 <= window <= MAX_CONTEXT_WINDOW:
        raise WebServiceError(
            f"Context window must be between 0 and {MAX_CONTEXT_WINDOW}"
        )
    return window


def safe_filename(filename: Optional[str]) -> str:
    """
    Reduce a client-supplied name to a bare filename.

    Browsers send ``C:\\fakepath\\app.py`` for a file input, and a hostile
    client sends whatever it likes. The name is only ever used to choose a
    language adapter and to label the session, so everything up to the last
    separator is dropped rather than interpreted.
    """
    raw = (filename or '').strip()
    if not raw:
        raise WebServiceError(
            "A filename is required — it selects the language adapter."
        )

    # Both separators, whatever platform the server runs on: a POSIX server
    # must still reduce a Windows path sent by a Windows browser.
    name = os.path.basename(raw.replace('\\', '/').rstrip('/'))
    name = name.strip().lstrip('.')

    if not name:
        raise WebServiceError(f"'{filename}' is not a usable filename.")
    return name


def resolve_language(filename: str) -> str:
    """
    Pick the language adapter for a filename, or explain what is supported.

    Never guesses: abstracting a file with the wrong parser produces output
    that looks abstracted and is not.
    """
    language = detect_language(Path(filename))
    if language is None:
        supported = ', '.join(
            ext for info in adapter_info() for ext in info.extensions
        )
        raise WebServiceError(
            f"No language adapter for '{filename}'. "
            f"Supported extensions: {supported}"
        )
    return language


def validate_source(code: Optional[str]) -> str:
    """Check the pasted source is present and within the size limit."""
    if code is None or not str(code).strip():
        raise WebServiceError("No source code was submitted.")

    text = str(code)
    size = len(text.encode('utf-8'))
    if size > MAX_SOURCE_BYTES:
        raise WebServiceError(
            f"Source is {size // 1024} KiB; "
            f"the limit is {MAX_SOURCE_BYTES // 1024} KiB.",
            status=413,
        )
    return text


def validate_query(query: Optional[str]) -> Optional[str]:
    """Bound a free-form question."""
    if query is None:
        return None
    text = str(query).strip()
    if not text:
        return None
    if len(text) > MAX_QUERY_CHARS:
        raise WebServiceError(
            f"Question is {len(text)} characters; "
            f"the limit is {MAX_QUERY_CHARS}."
        )
    return text


def validate_task(task: Optional[str]) -> str:
    """Check a preset task name."""
    value = (task or 'review').strip().lower()
    if value not in TASK_PROMPTS:
        raise WebServiceError(
            f"Unknown task '{task}'. "
            f"Choose one of: {', '.join(sorted(TASK_PROMPTS))}"
        )
    return value


# ═══════════════════════════════════════════════════════════
# Masking
# ═══════════════════════════════════════════════════════════
#
# mask_mapping_table / display_mapping moved to core.privacy_report: the
# CLI's `codeabstract translate` needed the exact same protection (it was
# calling RECONSTRUCT against the raw, unmasked mapping table -- a real
# leak, found by running the CLI end to end) and re-implementing it there
# would have let the two drift the way the underlying defect already
# proved they could. Both callers now share one function.


# ═══════════════════════════════════════════════════════════
# Results
# ═══════════════════════════════════════════════════════════

@dataclass
class VaultEntry:
    """One row of the local vault — the thing that never leaves the device."""

    token: str
    name: str
    label: str
    lineno: int
    occurrences: int
    scope: str
    detector: str
    confidence: float
    masked: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'token': self.token,
            'name': self.name,
            'label': self.label,
            'lineno': self.lineno,
            'occurrences': self.occurrences,
            'scope': self.scope,
            'detector': self.detector,
            'confidence': round(self.confidence, 2),
            'masked': self.masked,
        }


@dataclass
class AbstractionOutcome:
    """Everything one abstraction produced, ready to render or serialise."""

    session_id: str
    filename: str
    language: str
    privacy_level: str
    context_window: int
    original_code: str
    abstract_code: str
    statistics: Dict[str, Any]
    line_map: Dict[int, int]
    vault: List[VaultEntry]
    report: Any                       # core.privacy_report.PrivacyReport
    view_mapping: Dict[str, Dict]     # masked unless reveal — for highlighting
    saved: bool = False
    save_error: Optional[str] = None
    secrets_masked: bool = True

    @property
    def secrets_hidden(self) -> int:
        return self.report.hidden_by_label.get('SECRET', 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'filename': self.filename,
            'language': self.language,
            'privacy_level': self.privacy_level,
            'context_window': self.context_window,
            'abstract_code': self.abstract_code,
            'statistics': self.statistics,
            'line_map': {str(k): v for k, v in self.line_map.items()},
            'vault': [entry.to_dict() for entry in self.vault],
            'report': self.report.to_dict(),
            'report_markdown': self.report.to_markdown(),
            'headline': self.report.headline(),
            'secrets_hidden': self.secrets_hidden,
            'secrets_masked': self.secrets_masked,
            'saved': self.saved,
            'save_error': self.save_error,
        }


@dataclass
class ReviewOutcome:
    """An abstraction plus the round trip through a provider."""

    abstraction: AbstractionOutcome
    provider: str
    model: str
    task: Optional[str]
    query: Optional[str]
    abstract_query: Optional[str]
    query_redactions: int
    prompt_sha256: str
    raw_response: str
    mapped_feedback: str
    response_time: float
    attempts: int
    usage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = self.abstraction.to_dict()
        payload.update({
            'provider': self.provider,
            'model': self.model,
            'task': self.task,
            'query': self.query,
            'abstract_query': self.abstract_query,
            'query_redactions': self.query_redactions,
            'prompt_sha256': self.prompt_sha256,
            'raw_response': self.raw_response,
            'mapped_feedback': self.mapped_feedback,
            'response_time': round(self.response_time, 3),
            'attempts': self.attempts,
            'usage': self.usage,
        })
        return payload


# ═══════════════════════════════════════════════════════════
# The pipeline
# ═══════════════════════════════════════════════════════════

def _build_vault(view: Dict[str, Dict], reveal: bool) -> List[VaultEntry]:
    """Turn a mapping table into vault rows, ordered by where they appear."""
    entries = [
        VaultEntry(
            token=token,
            name=str(entry.get('name', '')),
            label=str(entry.get('label', 'IDENTIFIER')),
            lineno=int(entry.get('lineno', 0) or 0),
            occurrences=len(entry.get('occurrences', []) or []) or 1,
            scope=str(entry.get('scope', '')),
            detector=str(entry.get('detector', 'unspecified')),
            confidence=float(entry.get('confidence', 1.0)),
            masked=(entry.get('label') == 'SECRET' and not reveal),
        )
        for token, entry in view.items()
    ]
    entries.sort(key=lambda e: (e.lineno, e.token))
    return entries


def run_abstraction(
    code: str,
    filename: str,
    privacy_level: str = 'high',
    context_window: int = 3,
    keep_comments: bool = False,
    reveal: bool = False,
    save: bool = True,
) -> AbstractionOutcome:
    """
    ABSTRACT(S, k) for a browser submission.

    Args:
        code: The pasted or uploaded source. Content, never a path.
        filename: Name used to pick the adapter and label the session.
        privacy_level: ``low`` | ``medium`` | ``high`` | ``critical``.
        context_window: Context window k.
        keep_comments: Re-inject screened comments (stripped by default).
        reveal: Show secret values unmasked. Off by default.
        save: Persist the session, so a later translate can resolve tokens.

    Returns:
        An :class:`AbstractionOutcome`.

    Raises:
        WebServiceError: On invalid input, or if the source does not parse.
    """
    source = validate_source(code)
    name = safe_filename(filename)
    language = resolve_language(name)
    level = validate_privacy(privacy_level)
    window = validate_context_window(context_window)

    try:
        result = abstract_file(
            path=Path(name),
            source_code=source,
            context_window=window,
            privacy_level=level,
            # No project rules: an uploaded buffer has no repository around
            # it, and reading a .codeabstractignore from the *server's* tree
            # would apply a stranger's overrides to the user's code.
            overrides=None,
            keep_comments=keep_comments,
        )
    except SyntaxError as exc:
        raise WebServiceError(
            f"{name} does not parse as {language}: {exc.msg} (line {exc.lineno})"
        )
    except ValueError as exc:
        raise WebServiceError(str(exc))
    except Exception as exc:                       # pragma: no cover - defensive
        raise WebServiceError(f"Abstraction failed: {exc}", status=500)

    mapping_table = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
    view = display_mapping(mapping_table, reveal=reveal)

    report = build_report(
        mapping_table=mapping_table,
        statistics=result.statistics,
        kept=result.kept,
        session_id=result.session_id,
        source_file=name,
        privacy_level=level,
        language=result.language,
        reveal=reveal,
    )

    outcome = AbstractionOutcome(
        session_id=result.session_id,
        filename=name,
        language=result.language,
        privacy_level=level,
        context_window=window,
        original_code=source,
        abstract_code=result.abstract_code,
        statistics=dict(result.statistics),
        line_map=dict(result.line_map),
        vault=_build_vault(view, reveal),
        report=report,
        view_mapping=view,
        secrets_masked=not reveal,
    )

    if save:
        _persist(result, outcome)

    if audit_log.logging_enabled():
        try:
            audit_log.record_abstraction(
                session_id=result.session_id,
                # Marked as a web submission rather than dressed up as a
                # path: no such file exists on this machine, and a
                # compliance reviewer should not go looking for one.
                source_file=f"<web>/{name}",
                privacy_level=level,
                statistics=result.statistics,
                language=result.language,
            )
        except OSError:
            # An unwritable log must not lose the user their abstraction.
            # The gap stays visible to `codeabstract audit verify`, which is
            # where a missing entry belongs.
            pass

    return outcome


def _persist(result, outcome: AbstractionOutcome) -> None:
    """Save the session, recording rather than raising on failure."""
    try:
        save_session(
            session_id=result.session_id,
            source_file_path=f"<web>/{outcome.filename}",
            context_window=outcome.context_window,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key,
            statistics=result.statistics,
            line_map=result.line_map,
            language=result.language,
        )
        outcome.saved = True
    except Exception as exc:
        outcome.saved = False
        outcome.save_error = str(exc)


def run_translation(
    session_id: str,
    response_text: str,
    reveal: bool = False,
) -> Dict[str, Any]:
    """
    RECONSTRUCT(R, M̃, K) against a stored session.

    Args:
        session_id: Full ID or unambiguous prefix.
        response_text: The LLM's answer, in tokens.
        reveal: Show secret values unmasked in the restored text.

    Returns:
        ``{'session_id', 'filename', 'language', 'text', 'view_mapping', …}``.

    Raises:
        WebServiceError: Unknown or ambiguous session, or empty response.
    """
    text = (response_text or '').strip()
    if not text:
        raise WebServiceError("No LLM response was submitted.")

    session = _load(session_id)
    mapping_table = decrypt_mapping(
        session['encrypted_mapping'], session['encryption_key'],
    )
    view = display_mapping(mapping_table, reveal=reveal)

    # Reconstruct against the *masked* table, so a credential is never
    # written into the text in the first place. Redacting an already
    # rendered string is the weaker order: it has to find the value again,
    # and a short secret would over-match.
    encrypted_view, view_key = encrypt_mapping(view)

    restored = reconstruct(
        llm_response=text,
        encrypted_mapping=encrypted_view,
        encryption_key=view_key,
        line_map=session.get('line_map'),
    )

    seen = set(TOKEN_PATTERN.findall(text))
    return {
        'session_id': session['session_id'],
        'filename': session.get('source_file_path', ''),
        'language': session.get('language', 'python'),
        'created_at': session.get('created_at', ''),
        'text': restored,
        'view_mapping': view,
        'tokens_seen': len(seen),
        'tokens_resolved': sum(1 for token in seen if token in view),
        'secrets_masked': not reveal,
    }


def run_review(
    code: str,
    filename: str,
    task: str = 'review',
    query: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    privacy_level: str = 'high',
    context_window: int = 3,
    keep_comments: bool = False,
    reveal: bool = False,
    save: bool = True,
    client=None,
) -> ReviewOutcome:
    """
    Abstract → LLM → Reconstruct, driven from the browser.

    The provider client is built *before* the file is abstracted, for the
    same reason ``commands/review_cmd.py`` does: failing on a missing key
    after doing the work wastes time and tells the user nothing they could
    not have been told up front.

    Args:
        client: An already-built client, which bypasses provider
            resolution. Present so the tests can drive the whole route
            without an API key or a network call.

    Returns:
        A :class:`ReviewOutcome`.

    Raises:
        WebServiceError: Invalid input, no usable provider (503), or a
            provider error (502) — the failure is upstream, not in the
            request that reached us.
    """
    chosen_task = validate_task(task)
    question = validate_query(query)

    if client is None:
        try:
            client = create_client(api_key=api_key, provider=provider, model=model)
        except ProviderError as exc:
            raise WebServiceError(str(exc), status=503)

    outcome = run_abstraction(
        code=code,
        filename=filename,
        privacy_level=privacy_level,
        context_window=context_window,
        keep_comments=keep_comments,
        reveal=reveal,
        save=save,
    )

    # The question names the very things the code just stopped naming, so
    # it goes through the same mapping before it is allowed near a payload.
    abstract_question: Optional[str] = None
    redactions = 0
    mapping_table: Optional[Dict[str, Dict]] = None

    if question:
        mapping_table = _mapping_for(outcome)
        abstracted = abstract_query(question, mapping_table)
        abstract_question = abstracted.text
        redactions = len(abstracted.mapping_additions)

        if abstracted.mapping_additions:
            # A secret that appears only in the question still has to
            # resolve on the way back, so it joins the stored mapping.
            mapping_table.update(abstracted.mapping_additions)
            if outcome.saved:
                _rewrite_session_mapping(outcome, mapping_table)

    response = client.send(
        abstract_code=outcome.abstract_code,
        task=chosen_task,
        query=abstract_question,
        language=outcome.language,
    )

    prompt = build_prompt(
        outcome.abstract_code,
        task=chosen_task,
        query=abstract_question,
        language=outcome.language,
    )
    prompt_sha = audit_log.payload_digest(prompt)

    if audit_log.logging_enabled():
        try:
            audit_log.record_request(
                session_id=outcome.session_id,
                source_file=f"<web>/{outcome.filename}",
                provider=getattr(client, 'provider', 'unknown'),
                model=getattr(client, 'model', 'unknown'),
                privacy_level=outcome.privacy_level,
                payload_sha256=prompt_sha,
                response=response,
                language=outcome.language,
                task=None if question else chosen_task,
                free_form_query=bool(question),
            )
        except OSError:
            pass

    if not response.success:
        raise WebServiceError(
            f"{getattr(client, 'provider', 'provider')} error after "
            f"{response.attempts} attempt(s): {response.error}",
            status=502,
        )

    if outcome.saved:
        mapped = run_translation(
            outcome.session_id, response.content, reveal=reveal,
        )['text']
    else:
        mapped = _reconstruct_in_memory(
            response.content, mapping_table, outcome, reveal,
        )

    return ReviewOutcome(
        abstraction=outcome,
        provider=getattr(client, 'provider', 'unknown'),
        model=getattr(client, 'model', 'unknown'),
        task=None if question else chosen_task,
        query=question,
        abstract_query=abstract_question,
        query_redactions=redactions,
        prompt_sha256=prompt_sha,
        raw_response=response.content,
        mapped_feedback=mapped,
        response_time=response.response_time,
        attempts=response.attempts,
        usage=response.usage.to_dict(),
    )


def _mapping_for(outcome: AbstractionOutcome) -> Dict[str, Dict]:
    """
    The real (unmasked) mapping behind an outcome.

    Read back from the session when there is one, since that is the copy a
    later translate will use and therefore the copy a query's additions
    must join. An unsaved run has only the vault, which is enough to
    tokenise a question against.
    """
    if outcome.saved:
        session = _load(outcome.session_id)
        return decrypt_mapping(
            session['encrypted_mapping'], session['encryption_key'],
        )
    return {
        entry.token: {
            'name': entry.name,
            'label': entry.label,
            'lineno': entry.lineno,
        }
        for entry in outcome.vault
    }


def _reconstruct_in_memory(
    text: str,
    mapping_table: Optional[Dict[str, Dict]],
    outcome: AbstractionOutcome,
    reveal: bool,
) -> str:
    """Reconstruct without a stored session (``save=False`` runs)."""
    table = mapping_table if mapping_table is not None else _mapping_for(outcome)
    view = display_mapping(table, reveal=reveal)
    encrypted, key = encrypt_mapping(view)
    return reconstruct(
        llm_response=text,
        encrypted_mapping=encrypted,
        encryption_key=key,
        line_map=outcome.line_map,
    )


def _rewrite_session_mapping(outcome: AbstractionOutcome, mapping_table: Dict) -> None:
    """
    Replace a saved session's mapping after the query added secrets to it.

    Delete-then-save rather than an UPDATE: ``save_session`` owns where the
    key lives, and writing the row directly here would leave the old key
    orphaned in the key store.
    """
    try:
        encrypted, key = encrypt_mapping(mapping_table)
        delete_session(outcome.session_id)
        save_session(
            session_id=outcome.session_id,
            source_file_path=f"<web>/{outcome.filename}",
            context_window=outcome.context_window,
            encrypted_mapping=encrypted,
            encryption_key=key,
            statistics=outcome.statistics,
            line_map=outcome.line_map,
            language=outcome.language,
        )
    except Exception as exc:                       # pragma: no cover - defensive
        outcome.saved = False
        outcome.save_error = str(exc)


# ═══════════════════════════════════════════════════════════
# Sessions
# ═══════════════════════════════════════════════════════════

def _load(session_id: str) -> Dict[str, Any]:
    """Load a session, translating storage errors into HTTP-shaped ones."""
    key = (session_id or '').strip()
    if not key:
        raise WebServiceError("A session ID is required.")
    try:
        return load_session(key)
    except ValueError as exc:
        # "no such session" is 404; an ambiguous prefix is 409, because the
        # sessions exist and the client under-specified which one it meant.
        status = 409 if 'Ambiguous' in str(exc) else 404
        raise WebServiceError(str(exc), status=status)


def recent_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """Recent sessions, newest first, with no mapping material in them."""
    try:
        bound = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        bound = 20

    return [
        {
            'session_id': row.get('session_id', ''),
            'short_id': str(row.get('session_id', ''))[:12],
            'source_file': row.get('source_file_path', ''),
            'created_at': row.get('created_at', ''),
            'language': row.get('language', 'python'),
            'context_window': row.get('context_window', 3),
            'statistics': row.get('statistics', {}),
        }
        for row in list_sessions(limit=bound)
    ]


def session_detail(session_id: str, reveal: bool = False) -> Dict[str, Any]:
    """One session's metadata and its vault, masked by default."""
    session = _load(session_id)
    mapping_table = decrypt_mapping(
        session['encrypted_mapping'], session['encryption_key'],
    )
    view = display_mapping(mapping_table, reveal=reveal)
    return {
        'session_id': session['session_id'],
        'short_id': session['session_id'][:12],
        'source_file': session.get('source_file_path', ''),
        'created_at': session.get('created_at', ''),
        'language': session.get('language', 'python'),
        'context_window': session.get('context_window', 3),
        'statistics': session.get('statistics', {}),
        'vault': [entry.to_dict() for entry in _build_vault(view, reveal)],
        'secrets_masked': not reveal,
    }


def remove_session(session_id: str) -> Dict[str, Any]:
    """Delete a session and its key."""
    session = _load(session_id)
    deleted = delete_session(session['session_id'])
    return {'session_id': session['session_id'], 'deleted': bool(deleted)}


# ═══════════════════════════════════════════════════════════
# Capability reporting
# ═══════════════════════════════════════════════════════════

def provider_options() -> List[Dict[str, Any]]:
    """
    Provider readiness for the UI's selector.

    Installation and key presence stay separate, as they do in
    ``codeabstract providers list``: "no package" and "no key" need
    different fixes, and collapsing them sends the user to the wrong one.
    """
    options = []
    for status in provider_status():
        if not status['installed']:
            hint = f"pip install 'codeabstract[{status['extra']}]'"
        elif not status['has_key']:
            hint = f"set {' or '.join(status['env_vars'])}"
        else:
            hint = ''

        options.append({
            'provider': status['provider'],
            'installed': status['installed'],
            'has_key': status['has_key'],
            'ready': status['installed'] and status['has_key'],
            'model': status['model'],
            'is_default': status['is_default'],
            'hint': hint,
        })
    return options


def language_options() -> List[Dict[str, Any]]:
    """Registered language adapters and whether they are usable here."""
    return [
        {
            'language': info.language,
            'extensions': list(info.extensions),
            'available': info.available,
            'reason': info.reason,
        }
        for info in adapter_info()
    ]


def privacy_options() -> List[Dict[str, Any]]:
    """The four privacy levels, in increasing order of strictness."""
    return [
        {'level': name, 'description': spec['description']}
        for name, spec in PRIVACY_LEVELS.items()
    ]


def task_options() -> List[str]:
    """Preset task names the review endpoint accepts."""
    return sorted(TASK_PROMPTS)
