"""
Highlighting for the side-by-side panels.

Phase 5. The proposal's Option B mock-up asks for "interactive UI with code
highlighting and suggestions", which in this system means three specific
things, one per panel:

* **Abstract pane** — every token is marked with the label that produced it
  and carries the original name it stands for, so the user can read the
  thing the model is about to see and know what each placeholder was.
* **Original pane** — every line a symbol was taken from is marked with the
  strongest label on that line, so "what did this hide" is answerable by
  looking rather than by cross-referencing the vault.
* **Feedback pane** — the names RECONSTRUCT restored are marked, and any
  token it could *not* resolve is marked differently. An unresolved token
  is the one failure mode of the round trip that is otherwise invisible:
  the text still reads fine, it is just wrong.

Two properties this module has to hold, both tested:

**Everything is escaped.** The input is somebody's source code, which
routinely contains ``<``, ``&`` and quotes, and may contain a ``<script>``
tag either by accident or on purpose. Text is escaped first and markup is
only ever added afterwards, so the templates can render the result with
``|safe`` without that being a lie. Escaping first is safe for tokens
specifically because ``html.escape`` produces no ``PREFIX_<digits>``
sequence and alters none.

**Substitution is collision-safe.** ``VAR_1`` must not match inside
``VAR_10``, and the display name of one symbol must not be rewritten inside
a longer name that contains it. Same two guards as
``algorithms.reconstruct._substitute_tokens``: one pass, and a word-bounded
longest-first alternation.
"""

import html
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from web.service import TOKEN_PATTERN

# Label → CSS class. Anything unrecognised falls back to the identifier
# style rather than going unmarked, so a new label added to the classifier
# shows up as highlighted-but-plain instead of silently disappearing.
LABEL_CLASSES: Dict[str, str] = {
    'SECRET': 'tok-secret',
    'VALUE': 'tok-value',
    'IDENTIFIER': 'tok-identifier',
}
DEFAULT_LABEL_CLASS = 'tok-identifier'

# Which label wins when several sit on one line. A line that bound a
# credential is a secret line, whatever else it also did.
LABEL_RANK: Dict[str, int] = {'SECRET': 3, 'VALUE': 2, 'IDENTIFIER': 1}


def label_class(label: str) -> str:
    """CSS class for a classifier label."""
    return LABEL_CLASSES.get(label, DEFAULT_LABEL_CLASS)


@dataclass
class CodeLine:
    """One rendered line of either pane."""

    number: int
    html: str
    linked: Optional[int] = None      # paired line in the other pane
    label: str = ''                   # strongest label on this line
    tokens: List[str] = field(default_factory=list)

    @property
    def css(self) -> str:
        return label_class(self.label) if self.label else ''


# ═══════════════════════════════════════════════════════════
# Panes
# ═══════════════════════════════════════════════════════════

def highlight_abstract_code(
    abstract_code: str,
    view_mapping: Dict[str, Dict],
    line_map: Optional[Dict] = None,
) -> List[CodeLine]:
    """
    Mark every token in the code that is about to be sent.

    Args:
        abstract_code: The abstracted source.
        view_mapping: Mapping table **as the browser may see it** — masked
            unless the caller asked to reveal. This function never receives
            the raw table, so it cannot put a credential in a tooltip.
        line_map: ``{abstract_lineno: original_lineno}`` from ABSTRACT,
            used to pair the two panes.

    Returns:
        One :class:`CodeLine` per line of *abstract_code*.
    """
    pairs = _normalise_line_map(line_map)
    lines: List[CodeLine] = []

    for index, raw in enumerate(abstract_code.split('\n'), start=1):
        marked, tokens = _mark_tokens(raw, view_mapping)
        lines.append(CodeLine(
            number=index,
            html=marked,
            linked=pairs.get(index),
            label=_strongest(
                view_mapping.get(token, {}).get('label', '') for token in tokens
            ),
            tokens=tokens,
        ))
    return lines


def highlight_original_code(
    original_code: str,
    view_mapping: Dict[str, Dict],
) -> List[CodeLine]:
    """
    Mark the lines of the developer's own file that gave up a symbol.

    Every occurrence counts, not just the binding site: a credential read
    on five lines was exposed on five lines, and marking only its
    definition would understate that.

    Args:
        original_code: The submitted source, unmodified.
        view_mapping: Masked mapping table.

    Returns:
        One :class:`CodeLine` per line of *original_code*.
    """
    by_line: Dict[int, List[str]] = {}
    for token, entry in view_mapping.items():
        for lineno in _lines_of(entry):
            by_line.setdefault(lineno, []).append(token)

    lines: List[CodeLine] = []
    for index, raw in enumerate(original_code.split('\n'), start=1):
        tokens = sorted(set(by_line.get(index, [])))
        lines.append(CodeLine(
            number=index,
            html=html.escape(raw),
            linked=index,
            label=_strongest(
                view_mapping.get(token, {}).get('label', '') for token in tokens
            ),
            tokens=tokens,
        ))
    return lines


def highlight_feedback(text: str, view_mapping: Dict[str, Dict]) -> str:
    """
    Mark restored names, and flag any token that did not resolve.

    RECONSTRUCT emits ``original_name (line N)`` for each token it knew.
    Those get a ``restored`` mark carrying the token they came from, which
    is what makes the feedback traceable back to the abstraction rather
    than merely readable.

    Anything still matching the token pattern afterwards is a token
    RECONSTRUCT could not resolve — a model inventing ``VAR_99``, or a
    response pasted against the wrong session. It is marked as unresolved
    rather than left looking like ordinary prose.

    Args:
        text: Output of :func:`algorithms.reconstruct.reconstruct`.
        view_mapping: Masked mapping table, token → entry.

    Returns:
        Escaped HTML with ``<mark>`` elements added.
    """
    escaped = html.escape(text)

    # token → escaped display name, longest name first so a name that
    # contains another is matched whole.
    by_name: Dict[str, str] = {}
    for token, entry in view_mapping.items():
        name = html.escape(str(entry.get('name', '')))
        if name:
            by_name.setdefault(name, token)

    if by_name:
        names = sorted(by_name, key=len, reverse=True)
        restored = re.compile(
            r'(' + '|'.join(re.escape(n) for n in names) + r')'
            r'(\s\(line\s\d+\))'
        )

        def _restore(match: "re.Match") -> str:
            name, suffix = match.group(1), match.group(2)
            token = by_name[name]
            entry = view_mapping.get(token, {})
            return (
                f'<mark class="restored {label_class(str(entry.get("label", "")))}" '
                f'data-token="{html.escape(token, quote=True)}">'
                f'{name}{suffix}</mark>'
            )

        escaped = restored.sub(_restore, escaped)

    # Whatever still looks like a token was never resolved.
    def _unresolved(match: "re.Match") -> str:
        token = match.group(1)
        return f'<mark class="unresolved" data-token="{token}">{token}</mark>'

    return TOKEN_PATTERN.sub(_unresolved, escaped)


def highlight_token_text(text: str, view_mapping: Dict[str, Dict]) -> str:
    """
    Escape a block of tokenised text and mark every token in it.

    Used for the raw-response pane, which shows the provider's answer
    exactly as it came back — still in tokens, before RECONSTRUCT touches
    it. Showing that pane at all is the point: it is the evidence that the
    model only ever saw placeholders.

    Tokens the mapping knows get the same marks as the abstract pane;
    tokens it does not are marked unresolved, since those are the ones that
    will still be tokens after reconstruction.
    """
    escaped = html.escape(text)

    def _wrap(match: "re.Match") -> str:
        token = match.group(1)
        entry = view_mapping.get(token)
        if entry is None:
            return f'<mark class="unresolved" data-token="{token}">{token}</mark>'
        return _token_span(token, entry)

    return TOKEN_PATTERN.sub(_wrap, escaped)


def highlight_vault_rows(vault: Sequence) -> List[Dict[str, str]]:
    """
    Escape vault rows for the local-vault panel.

    The vault holds the original names — the payload of the whole exercise.
    It is rendered on the page, so it is escaped here rather than trusting
    every template that touches it.
    """
    rows = []
    for entry in vault:
        data = entry.to_dict() if hasattr(entry, 'to_dict') else dict(entry)
        rows.append({
            'token': html.escape(str(data.get('token', ''))),
            'name': html.escape(str(data.get('name', ''))),
            'label': html.escape(str(data.get('label', ''))),
            'css': label_class(str(data.get('label', ''))),
            'lineno': str(data.get('lineno', 0)),
            'occurrences': str(data.get('occurrences', 0)),
            'scope': html.escape(str(data.get('scope', ''))),
            'detector': html.escape(str(data.get('detector', ''))),
            'confidence': f"{float(data.get('confidence', 1.0)):.2f}",
            'masked': bool(data.get('masked', False)),
            'signals': html.escape(_signals_text(data.get('signals') or {})),
        })
    return rows


def _signals_text(signals: dict) -> str:
    """
    A short "why" summary from the shape features in ``signals``.

    Built here, not in the client, so the single place already responsible
    for what is safe to put on the page is also the one assembling this
    string — see the module docstring.
    """
    if not signals:
        return ''
    parts = [
        f"{signals['length']} chars",
        f"entropy {signals['entropy']:.1f}",
        str(signals['case_style']),
    ]
    if signals.get('digit_ratio', 0) >= 0.3:
        parts.append(f"{signals['digit_ratio'] * 100:.0f}% digits")
    if signals.get('looks_like_url'):
        parts.append('URL-shaped')
    return ' · '.join(parts)


# ═══════════════════════════════════════════════════════════
# Internals
# ═══════════════════════════════════════════════════════════

def _mark_tokens(line: str, view_mapping: Dict[str, Dict]):
    """
    Escape one line, then wrap the tokens in it.

    Returns (html, tokens_found). Only tokens present in the mapping are
    wrapped: a bare ``VAR_9`` typed into the source by the user is not a
    token this abstraction produced, and dressing it up as one would be a
    claim the mapping cannot back.
    """
    escaped = html.escape(line)
    found: List[str] = []

    def _wrap(match: "re.Match") -> str:
        token = match.group(1)
        entry = view_mapping.get(token)
        if entry is None:
            return token

        found.append(token)
        return _token_span(token, entry)

    marked = TOKEN_PATTERN.sub(_wrap, escaped)
    # Deduplicate, keeping first-occurrence order.
    ordered: List[str] = []
    for token in found:
        if token not in ordered:
            ordered.append(token)
    return marked, ordered


def _token_span(token: str, entry: Dict) -> str:
    """
    One token, wrapped with what it stands for.

    The tooltip carries the *display* name, which is masked for secrets —
    the mapping reaching this module is already the browser-safe view, so
    the mask is applied upstream and this is only the last place it could
    have been undone.
    """
    name = html.escape(str(entry.get('name', '')), quote=True)
    label = str(entry.get('label', ''))
    lineno = html.escape(str(entry.get('lineno', 0)), quote=True)
    return (
        f'<span class="tok {label_class(label)}" '
        f'data-token="{html.escape(token, quote=True)}" '
        f'data-line="{lineno}" '
        f'title="{name} — {html.escape(label, quote=True)}, '
        f'original line {lineno}">'
        f'{token}</span>'
    )


def _lines_of(entry: Dict) -> List[int]:
    """Every original line a mapping entry touches."""
    lines = {int(entry.get('lineno', 0) or 0)}
    for occurrence in entry.get('occurrences', []) or []:
        try:
            lines.add(int(occurrence.get('lineno', 0) or 0))
        except (AttributeError, TypeError, ValueError):
            continue
    return [line for line in lines if line > 0]


def _strongest(labels) -> str:
    """The highest-ranked label in an iterable, or ''."""
    best, rank = '', 0
    for label in labels:
        score = LABEL_RANK.get(label, 0)
        if score > rank:
            best, rank = label, score
    return best


def _normalise_line_map(line_map: Optional[Dict]) -> Dict[int, int]:
    """
    Coerce a line map to ``{int: int}``.

    JSON round-trips turn the keys into strings — the session store writes
    the index as JSON, and the browser posts it back the same way — so both
    forms have to be accepted here or the panes silently stop pairing.
    """
    if not line_map:
        return {}

    pairs: Dict[int, int] = {}
    for key, value in line_map.items():
        try:
            pairs[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return pairs
