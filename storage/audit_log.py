"""
Append-Only Audit Log

Phase 4 — the "audit log" workstream. The proposal names this as the
compliance deliverable: a local record of every outbound request, so that
an organisation can answer "what did this tool send, and when" without
taking anyone's word for it.

Design decisions worth stating, because each one is a place where an audit
log can quietly become useless:

* **It records metadata, never content.** No source code, no identifier
  names, no prompt text, no response text. An audit log that quoted the
  outbound payload would hold the very material the rest of the system
  exists to keep out of reach — a leak with a timestamp on it. What it
  stores instead is the SHA-256 of the payload, which is enough to prove
  that a given file was or was not what left the machine.

* **It is hash-chained.** Every entry carries the hash of the previous
  one, so removing or editing an entry breaks every hash after it and
  :func:`verify_chain` says where. This is tamper *evidence*, not tamper
  *proofing* — anyone who can write the file can rewrite the whole chain.
  Detecting selective edits is the realistic goal for a local file, and
  claiming more would be dishonest.

* **It is append-only by construction.** Entries are written with ``'a'``
  and never rewritten. Nothing in the codebase deletes or edits a line.

* **A failure to log does not fail the run**, but it is never silent: the
  caller gets the exception back to report. Losing the user's review
  because the audit file is read-only would make people turn logging off,
  which is worse for compliance than a warning.

Format is JSON Lines: one self-describing object per line, greppable, and
readable without this module.
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import __version__, detector_version, get_audit_log_path

# First entry's ``prev``. A fixed sentinel rather than an empty string, so
# that a truncated file cannot be mistaken for a complete one.
GENESIS = "genesis"

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def payload_digest(text: str) -> str:
    """
    Hash of an outbound payload, for recording what was sent.

    The hash is over the exact bytes the provider received, so it can be
    recomputed later from the abstracted file and compared. It reveals
    nothing about the content on its own.
    """
    return _digest(text)


def _canonical(entry: Dict[str, Any]) -> str:
    """Stable serialisation for hashing: sorted keys, no whitespace drift."""
    return json.dumps(entry, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# Writing
# ═══════════════════════════════════════════════════════════

def _last_entry(path: Path) -> Optional[Dict[str, Any]]:
    """Read the final entry, or None for an empty or absent log."""
    if not path.is_file():
        return None
    last = None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line:
                    last = line
    except OSError:
        return None

    if last is None:
        return None
    try:
        return json.loads(last)
    except ValueError:
        return None


def append_entry(
    event: str,
    path: Optional[Path] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """
    Append one record and return it.

    Args:
        event: What happened — ``abstract``, ``request``, ``apply``,
            ``reconstruct``.
        path: Log file; defaults to ``~/.codeabstract/audit.log``.
        **fields: Metadata for the entry. Callers should pass only
            metadata; see the module docstring on why content never goes
            in here.

    Returns:
        The written entry, including its ``seq``, ``prev`` and ``hash``.

    Raises:
        OSError: If the log cannot be written.
    """
    log_path = Path(path) if path else get_audit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    previous = _last_entry(log_path)
    entry: Dict[str, Any] = {
        'schema': SCHEMA_VERSION,
        'seq': (previous['seq'] + 1) if previous and 'seq' in previous else 1,
        'timestamp': _now(),
        'event': event,
        'tool_version': __version__,
        'detector_version': detector_version(),
        'prev': previous.get('hash', GENESIS) if previous else GENESIS,
    }
    entry.update({k: v for k, v in fields.items() if v is not None})
    entry['hash'] = _digest(_canonical(entry))

    with open(log_path, 'a', encoding='utf-8') as handle:
        handle.write(_canonical(entry) + "\n")

    return entry


def record_abstraction(
    session_id: str,
    source_file: str,
    privacy_level: str,
    statistics: Dict[str, Any],
    language: str = "python",
    path: Optional[Path] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Log an abstraction, whether or not anything is later sent anywhere.

    Abstracting is the moment the detector made its decisions, so it is the
    moment worth recording: a run that never reached a provider still
    produced a privacy report someone may need to account for.

    Args:
        user_id: The web account this abstraction belongs to, if any. Only
            ever set by web/service.py -- the CLI has no such concept, and
            its entries carry no owner (see web.service.audit_overview,
            which is what filters by this field; ``codeabstract audit
            list`` reads every entry regardless of it).
    """
    return append_entry(
        'abstract',
        path=path,
        session_id=session_id,
        source_file=str(source_file),
        language=language,
        privacy_level=privacy_level,
        user_id=user_id,
        counts={
            'abstracted': statistics.get('abstracted_nodes', 0),
            'secrets': statistics.get('secrets_found', 0),
            'values': statistics.get('values_found', 0),
            'modules_abstracted': statistics.get('modules_abstracted', 0),
            'modules_preserved': statistics.get('modules_preserved', 0),
            'low_confidence': statistics.get('low_confidence_nodes', 0),
        },
    )


def record_request(
    session_id: str,
    source_file: str,
    provider: str,
    model: str,
    privacy_level: str,
    payload_sha256: str,
    response: Any = None,
    language: str = "python",
    task: Optional[str] = None,
    free_form_query: bool = False,
    path: Optional[Path] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Log one outbound request to an LLM provider.

    Args:
        session_id: Session the request belongs to.
        source_file: The developer's file — a path, never its contents.
        provider: Provider name.
        model: Model identifier.
        privacy_level: Level the code was abstracted at.
        payload_sha256: :func:`payload_digest` of what was sent.
        response: An :class:`llm.base.LLMResponse`, for token counts,
            latency and success.
        language: Source language.
        task: Preset task name, when one was used.
        free_form_query: True when the user asked their own question.
            Recorded because a free-form query is a second thing that left
            the machine, and a reviewer should be able to see that it did.
        path: Log file override.
        user_id: The web account this request belongs to, if any. See
            :func:`record_abstraction`.

    Returns:
        The written entry.
    """
    usage = getattr(response, 'usage', None)
    return append_entry(
        'request',
        path=path,
        session_id=session_id,
        source_file=str(source_file),
        language=language,
        privacy_level=privacy_level,
        provider=provider,
        model=model,
        task=task,
        free_form_query=free_form_query,
        user_id=user_id,
        payload_sha256=payload_sha256,
        success=bool(getattr(response, 'success', False)) if response else None,
        error=getattr(response, 'error', None) if response else None,
        attempts=getattr(response, 'attempts', None) if response else None,
        response_time=(
            round(getattr(response, 'response_time', 0.0), 4) if response else None
        ),
        tokens=usage.to_dict() if usage is not None else None,
    )


# ═══════════════════════════════════════════════════════════
# Reading and verification
# ═══════════════════════════════════════════════════════════

def read_entries(
    limit: Optional[int] = None,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Read entries oldest-first.

    Args:
        limit: Return only the most recent *limit* entries (still in
            chronological order).
        path: Log file override.

    Returns:
        A list of entries; empty if the log does not exist yet.
    """
    log_path = Path(path) if path else get_audit_log_path()
    if not log_path.is_file():
        return []

    entries: List[Dict[str, Any]] = []
    with open(log_path, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                # A malformed line is itself a finding; keep it visible
                # rather than dropping it silently.
                entries.append({'event': 'unparseable', 'raw': line})

    return entries[-limit:] if limit else entries


@dataclass
class ChainVerification:
    """Result of checking the hash chain."""

    ok: bool
    entries: int
    problems: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return f"{self.entries} entries, chain intact"
        return f"{self.entries} entries, {len(self.problems)} problem(s)"


def verify_chain(path: Optional[Path] = None) -> ChainVerification:
    """
    Check that every entry hashes to what it claims and links to the last.

    Detects a modified entry (its own hash no longer matches), a deleted
    one (the next entry's ``prev`` points at a hash that is not there), and
    a reordered file. It cannot detect a wholesale rewrite of the entire
    chain — see the module docstring.

    Returns:
        :class:`ChainVerification` naming each problem by sequence number.
    """
    entries = read_entries(path=path)
    problems: List[str] = []
    expected_prev = GENESIS

    for index, entry in enumerate(entries, start=1):
        label = f"entry {entry.get('seq', index)}"

        if 'hash' not in entry:
            problems.append(f"{label}: no hash — line is not a valid record")
            expected_prev = None
            continue

        body = {k: v for k, v in entry.items() if k != 'hash'}
        recomputed = _digest(_canonical(body))
        if recomputed != entry['hash']:
            problems.append(f"{label}: contents do not match its hash — modified")

        if expected_prev is not None and entry.get('prev') != expected_prev:
            problems.append(
                f"{label}: links to {str(entry.get('prev'))[:12]}…, "
                f"expected {expected_prev[:12]}… — an entry was removed or reordered"
            )

        expected_prev = entry['hash']

    return ChainVerification(ok=not problems, entries=len(entries), problems=problems)


def audit_log_path() -> Path:
    """Where the audit log lives."""
    return get_audit_log_path()


def logging_enabled() -> bool:
    """
    True unless the user turned logging off.

    ``CODEABSTRACT_NO_AUDIT`` in the environment overrides the config
    setting, so a scripted run can opt out without editing config.
    """
    if os.environ.get('CODEABSTRACT_NO_AUDIT'):
        return False
    from config.settings import get_config
    return bool(get_config().get('audit_log', True))
