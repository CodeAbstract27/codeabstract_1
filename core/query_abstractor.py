"""
Free-Form Query Abstraction

Phase 4 — the "free-form queries" workstream.

The proposal's input specification has *User Query* as a first-class field.
The CLI offered five fixed presets instead, which is a smaller product and,
more importantly, a smaller privacy problem — the presets contain no user
text, so nothing about them could leak.

A real question does not have that property. It is written by someone
looking at their own file, in their own names:

    "why does charge_customer fail when stripe_api_key is rotated?"

Sending that alongside abstracted code would hand back both halves of the
mapping in the same request: the code says ``FUNC_3`` and the question says
``charge_customer``, at which point the abstraction has protected nothing.
An observer does not even need to align them — the query names them.

So a query gets the same treatment as the code, using the same mapping:

* **Known identifiers become their tokens.** One pass, word-bounded,
  longest-first — the same collision-safe substitution RECONSTRUCT uses in
  the other direction (Phase 0 / D2).
* **Credential-shaped strings are redacted**, even when they appear
  nowhere in the file. People paste the failing key into the question.
  These mint fresh ``SECRET_n`` tokens which the caller merges into the
  mapping, so the answer still reconstructs.
* **Short names are left alone by default.** Substituting a two-letter
  identifier would rewrite ordinary English — a variable named ``as`` or
  ``in`` would shred the sentence. The threshold is a knob, and the
  trade-off is stated where it is set.

What this module does *not* do is judge whether a question is safe to ask.
It removes the identifiers and secrets it can recognise; prose describing
proprietary business logic in plain English is beyond any of the detectors
here, and the threat model (Phase 5) has to say so.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.secret_detector import is_secret_value

# Names shorter than this are not substituted into a query. Three is the
# point where an identifier stops colliding with common English words in
# practice; ``id``, ``to``, ``in`` and ``is`` are all two.
MIN_SUBSTITUTABLE_LENGTH = 3

# Candidate secrets in free text: quoted strings, or unbroken runs long
# enough to be a credential. Splitting on whitespace alone would miss
# ``key="sk_live_…"`` written without spaces.
_CANDIDATE = re.compile(r'"[^"]{6,}"|\'[^\']{6,}\'|[^\s`"\']{16,}')


@dataclass
class QueryAbstraction:
    """The abstracted query, and an account of what changed."""

    text: str
    original: str
    substitutions: List[Tuple[str, str]] = field(default_factory=list)
    redactions: List[str] = field(default_factory=list)
    # Fresh mapping entries for secrets found only in the query. The caller
    # merges these before encrypting, so RECONSTRUCT can resolve a token
    # the model echoes back.
    mapping_additions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.substitutions or self.redactions)

    def summary(self) -> str:
        return (
            f"{len(self.substitutions)} identifier(s) tokenised, "
            f"{len(self.redactions)} secret(s) redacted"
        )


def _next_secret_index(mapping_table: Dict[str, Dict]) -> int:
    """Find the first unused ``SECRET_n`` index in an existing mapping."""
    highest = -1
    for token in mapping_table:
        if token.startswith('SECRET_'):
            try:
                highest = max(highest, int(token.split('_', 1)[1]))
            except (IndexError, ValueError):
                continue
    return highest + 1


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def abstract_query(
    query: str,
    mapping_table: Optional[Dict[str, Dict]] = None,
    min_length: int = MIN_SUBSTITUTABLE_LENGTH,
) -> QueryAbstraction:
    """
    Rewrite a user's question so it can travel with abstracted code.

    Args:
        query: The question as typed.
        mapping_table: Decrypted mapping from the abstraction this query
            accompanies. Names in it are replaced by their tokens.
        min_length: Shortest identifier eligible for substitution.

    Returns:
        A :class:`QueryAbstraction`. ``mapping_additions`` must be merged
        into the mapping table before it is encrypted, or the tokens it
        mints will not resolve on the way back.

    Note:
        Redaction runs **before** substitution, so a credential pasted into
        the question cannot be partially rewritten by an identifier
        substitution first and then escape the secret detector.
    """
    text = query or ""
    mapping_table = mapping_table or {}

    redactions: List[str] = []
    additions: Dict[str, Dict[str, Any]] = {}
    next_index = _next_secret_index(mapping_table)

    # A secret pasted into the question is usually one already in the file.
    # Reusing its token keeps the code and the question consistent — two
    # tokens for one credential would read to the model as two credentials.
    known_secrets = {
        entry.get('name'): token
        for token, entry in mapping_table.items()
        if entry.get('label') == 'SECRET' and isinstance(entry.get('name'), str)
    }

    # ── Step 1: redact credential-shaped strings ──────────────
    def _redact(match: "re.Match") -> str:
        nonlocal next_index
        raw = match.group(0)
        value = _strip_quotes(raw)

        if not is_secret_value(value):
            return raw

        redactions.append(value)

        existing = known_secrets.get(value)
        if existing:
            return f"{raw[0]}{existing}{raw[0]}" if raw[0] in "\"'" else existing

        token = f"SECRET_{next_index}"
        next_index += 1
        additions[token] = {
            'name': value,
            'label': 'SECRET',
            'node_type': 'query',
            'lineno': 0,
            'ctx': {},
            'scope': 'query',
            'confidence': 0.95,
            'detector': 'query-secret',
            'evidence': ['credential-shaped string in the user query'],
            'occurrences': [],
        }
        # Preserve the quoting so the sentence still reads naturally.
        if raw and raw[0] in "\"'":
            return f"{raw[0]}{token}{raw[0]}"
        return token

    text = _CANDIDATE.sub(_redact, text)

    # ── Step 2: substitute known identifiers ──────────────────
    # Longest first so that ``charge`` cannot claim the ``charge`` inside
    # ``charge_customer``; one pass so no replacement is ever re-scanned.
    name_to_token: Dict[str, str] = {}
    for token, entry in mapping_table.items():
        name = entry.get('name')
        if not isinstance(name, str) or len(name) < min_length:
            continue
        # A name that is not a plain identifier (a string literal, a URL)
        # is not a word in a sentence; substituting it would mangle text
        # that merely happens to contain it.
        if not name.isidentifier():
            continue
        name_to_token.setdefault(name, token)

    substitutions: List[Tuple[str, str]] = []
    if name_to_token:
        ordered = sorted(name_to_token, key=len, reverse=True)
        pattern = re.compile(
            r'\b(' + '|'.join(re.escape(name) for name in ordered) + r')\b'
        )

        def _substitute(match: "re.Match") -> str:
            name = match.group(1)
            token = name_to_token[name]
            substitutions.append((name, token))
            return token

        text = pattern.sub(_substitute, text)

    return QueryAbstraction(
        text=text,
        original=query or "",
        substitutions=substitutions,
        redactions=redactions,
        mapping_additions=additions,
    )
