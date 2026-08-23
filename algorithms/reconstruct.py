"""
RECONSTRUCT(R, M̃, K) Algorithm Implementation

Implements formal Algorithm 3 from specification.

Translates abstract LLM responses back to human-readable feedback
by replacing tokens with original identifiers and appending
formatted source context blocks.
"""

import re
from typing import Dict, List, Optional

from algorithms.encrypt import decrypt_mapping


def reconstruct(
    llm_response: str,
    encrypted_mapping: bytes,
    encryption_key: bytes,
    line_map: Optional[Dict] = None,
) -> str:
    """
    RECONSTRUCT(R, M̃, K) — Context-Aware Reconstruction Algorithm.

    Decrypts the mapping table, finds all abstraction tokens in the
    LLM response, replaces them with ``original_name (line N)``
    references, and appends formatted source-context blocks.

    Args:
        llm_response: Abstract LLM response R containing tokens.
        encrypted_mapping: Encrypted mapping table M̃ (bytes).
        encryption_key: Encryption key K (bytes).
        line_map: Optional ``{abstract_lineno: original_lineno}`` index
            produced by ABSTRACT.  When supplied, line citations in the
            response are translated from the abstract code the LLM saw to
            the developer's own file.  Sessions created before Phase 1
            have no such index and are handled unchanged.

    Returns:
        Human-readable response F with original names and context.

    Raises:
        ValueError: If decryption of the mapping table fails.

    Implements:
        Algorithm 3 from formal specification.
    """
    # ───────────────────────────────────────────────────
    # Step 1: Decrypt mapping table
    # ───────────────────────────────────────────────────
    mapping_table: Dict = decrypt_mapping(encrypted_mapping, encryption_key)

    # ───────────────────────────────────────────────────
    # Step 1b: Translate line citations (Phase 1)
    # ───────────────────────────────────────────────────
    # Runs before token substitution so it cannot rewrite the
    # "(line N)" references this function is about to insert.
    llm_response = _translate_line_references(llm_response, line_map)

    # ───────────────────────────────────────────────────
    # Step 2: Extract tokens from response
    # ───────────────────────────────────────────────────
    tokens = _extract_tokens(llm_response)

    # ───────────────────────────────────────────────────
    # Step 3: Keep only tokens we can actually resolve
    # ───────────────────────────────────────────────────
    known_tokens = [t for t in tokens if t in mapping_table]

    # ───────────────────────────────────────────────────
    # Step 4: Collect context blocks (first-occurrence order)
    # ───────────────────────────────────────────────────
    context_blocks: List[Dict] = [
        {
            'name': mapping_table[token]['name'],
            'lineno': mapping_table[token]['lineno'],
            'ctx': mapping_table[token].get('ctx', {}),
            'scope': mapping_table[token].get('scope', ''),
            'occurrences': mapping_table[token].get('occurrences', []),
        }
        for token in known_tokens
    ]

    # ───────────────────────────────────────────────────
    # Step 5-11: Substitute every token in a single pass
    # ───────────────────────────────────────────────────
    final_response: str = _substitute_tokens(
        llm_response, known_tokens, mapping_table,
    )

    # ───────────────────────────────────────────────────
    # Step 12-13: Append formatted context blocks
    # ───────────────────────────────────────────────────
    if context_blocks:
        formatted_ctx = _format_context_blocks(context_blocks)
        final_response = f"{final_response}\n\n{formatted_ctx}"

    return final_response


# ═══════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════

_LINE_REFERENCE = re.compile(
    r'\b(lines?)(\s*#?\s*)(\d+)(\s*(?:[-–—]|to|through)\s*)?(\d+)?',
    re.IGNORECASE,
)


def _translate_line_references(text: str, line_map: Optional[Dict]) -> str:
    """
    Rewrite the LLM's line citations from abstract to original numbering.

    Phase 1.  The model only ever saw the unparsed abstract code, so
    "the bug is on line 4" refers to line 4 of a file the developer has
    never laid eyes on.  Comments and blank lines are dropped during
    unparsing, so the two numberings diverge almost immediately.

    Handles "line 4", "lines 4-6", "Line #4" and "lines 4 to 6".  A number
    with no entry in the index is left exactly as it was: a citation we
    cannot place is better shown unchanged than silently moved.

    Args:
        text: The raw LLM response.
        line_map: ``{abstract_lineno: original_lineno}``, or None.

    Returns:
        The response with translatable line numbers rewritten.
    """
    if not line_map:
        return text

    # JSON round-trips dict keys to strings; accept either form.
    index = {}
    for key, value in line_map.items():
        try:
            index[int(key)] = int(value)
        except (TypeError, ValueError):
            continue

    if not index:
        return text

    def _rewrite(match: "re.Match") -> str:
        word, spacer, start, joiner, end = match.groups()
        new_start = index.get(int(start))
        if new_start is None:
            return match.group(0)

        rebuilt = f"{word}{spacer}{new_start}"
        if joiner:
            # The joiner group is optional and matches even when no second
            # number follows it — "the bug on line 4 to prevent this" hands
            # us joiner=' to ', end=None.  The match already consumed that
            # text, so it has to be re-emitted unconditionally; dropping it
            # swallows the joiner and glues the surrounding prose together.
            rebuilt += joiner
            if end:
                new_end = index.get(int(end))
                if new_end is None:
                    return match.group(0)
                rebuilt += str(new_end)
        return rebuilt

    return _LINE_REFERENCE.sub(_rewrite, text)


def _substitute_tokens(
    text: str,
    tokens: List[str],
    mapping_table: Dict,
) -> str:
    """
    Replace every token in *text* with its human-readable reference.

    Phase 0 / D2: this replaces a per-token ``str.replace()`` loop, which
    corrupted any response containing both ``VAR_1`` and ``VAR_10`` — the
    shorter token substituted itself inside the longer one, leaving debris
    like ``variable_name (line 2)0`` and pointing the developer at the
    wrong line.

    Two independent guards prevent that here:

    1. **One pass.** A single ``re.sub`` over the original text means no
       substitution can ever be re-scanned, so replacement output is never
       itself treated as input.
    2. **Word-bounded, longest-first alternation.** ``\\bVAR_1\\b`` cannot
       match inside ``VAR_10`` (no word boundary between ``1`` and ``0``),
       and longer tokens are tried first regardless.

    Args:
        text: The LLM response.
        tokens: Tokens known to be present in the mapping table.
        mapping_table: Decrypted mapping table.

    Returns:
        The response with all known tokens substituted.
    """
    if not tokens:
        return text

    # Longest first, so a longer token always wins an overlapping match.
    ordered = sorted(set(tokens), key=len, reverse=True)
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(t) for t in ordered) + r')\b'
    )

    def _replace(match: "re.Match") -> str:
        entry = mapping_table[match.group(1)]
        return f"{entry['name']} (line {entry['lineno']})"

    return pattern.sub(_replace, text)


def _extract_tokens(text: str) -> List[str]:
    """
    Extract all abstraction tokens from text.

    Pattern: (FUNC|VAR|SECRET|CONST|NUM|CLASS|MODULE)_\\d+

    Returns a deduplicated list preserving first-occurrence order.
    """
    pattern = r'\b((?:FUNC|VAR|SECRET|CONST|NUM|CLASS|MODULE)_\d+)\b'
    matches = re.findall(pattern, text)

    # Deduplicate while preserving order
    seen = set()
    unique: List[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def _format_context_blocks(blocks: List[Dict]) -> str:
    """
    Format context blocks for appending to translated output.

    Produces a readable listing showing each referenced identifier
    with its surrounding source lines, with the target line marked.

    Format example::

        ─── Source Context ────────────────────────────────
        calculate_commission (line 45):

          43 │ commission_rate = 0.029
          44 │
        → 45 │ def calculate_commission(amount):
          46 │     return amount * commission_rate
          47 │

    """
    if not blocks:
        return ""

    lines = ["─── Source Context ────────────────────────────────"]

    for block in blocks:
        name = block.get('name', '???')
        lineno = block.get('lineno', '?')
        ctx = block.get('ctx', {})

        # Phase 1: the scope disambiguates identically-named symbols, which
        # now get separate tokens rather than being collapsed into one.
        scope = block.get('scope', '')
        location = f"{name} (line {lineno})"
        if scope and scope not in ('literal', 'attribute', 'import', 'module'):
            location = f"{name} in {scope}() (line {lineno})"

        occurrence_count = len(block.get('occurrences', []))
        if occurrence_count > 1:
            location += f" — {occurrence_count} occurrences"

        lines.append(f"\n{location}:\n")

        snippet = ctx.get('snippet', '')
        start_line = ctx.get('start_line', 1)
        target_line = ctx.get('target_line', lineno)

        if snippet:
            for i, line_text in enumerate(snippet.split('\n')):
                current_lineno = start_line + i
                marker = "→" if current_lineno == target_line else " "
                lines.append(f"{marker} {current_lineno:>4} │ {line_text}")
        else:
            lines.append("  (no context available)")

        lines.append("")  # Blank line after each block

    lines.append("───────────────────────────────────────────────────")
    return '\n'.join(lines)
