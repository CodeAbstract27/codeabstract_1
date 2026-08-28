"""
RECONSTRUCT(R, M̃, K) Algorithm Implementation

Implements formal Algorithm 3 from specification.

Translates abstract LLM responses back to human-readable feedback
by replacing tokens with original identifiers and appending
formatted source context blocks.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List

from algorithms.encrypt import decrypt_mapping


# ═══════════════════════════════════════════════════════════
# Structured result type
# ═══════════════════════════════════════════════════════════

@dataclass
class ReconstructResult:
    """Structured output from the reconstruct algorithm.

    Attributes:
        review_text: The review/feedback with clean identifier names
                     (no line-number noise).
        references:  Deduplicated list of referenced identifiers with
                     name, line number, type prefix, and source context.
    """
    review_text: str = ""
    references: List[Dict] = field(default_factory=list)

    def __str__(self) -> str:
        """Render the full output as a plain string (backward compat)."""
        parts = [self.review_text]
        if self.references:
            parts.append("")
            parts.append(_format_context_blocks(self.references))
        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# Token prefix → human-readable type label
# ═══════════════════════════════════════════════════════════

_PREFIX_LABELS = {
    "FUNC": "Function",
    "CLASS": "Class",
    "SECRET": "Secret",
    "VAR": "Variable",
    "CONST": "Constant",
    "NUM": "Number",
}


def reconstruct(
    llm_response: str,
    encrypted_mapping: bytes,
    encryption_key: bytes,
) -> str:
    """
    RECONSTRUCT(R, M̃, K) — Context-Aware Reconstruction Algorithm.

    Decrypts the mapping table, finds all abstraction tokens in the
    LLM response, replaces them with clean identifier names,
    and appends formatted source-context blocks.

    Args:
        llm_response: Abstract LLM response R containing tokens.
        encrypted_mapping: Encrypted mapping table M̃ (bytes).
        encryption_key: Encryption key K (bytes).

    Returns:
        Human-readable response F with original names and context.

    Raises:
        ValueError: If decryption of the mapping table fails.

    Implements:
        Algorithm 3 from formal specification.
    """
    result = reconstruct_structured(llm_response, encrypted_mapping, encryption_key)
    return str(result)


def reconstruct_structured(
    llm_response: str,
    encrypted_mapping: bytes,
    encryption_key: bytes,
) -> ReconstructResult:
    """
    RECONSTRUCT(R, M̃, K) — Structured Reconstruction.

    Like ``reconstruct()`` but returns a ``ReconstructResult`` so
    callers can render the review text and reference table separately.

    Args:
        llm_response: Abstract LLM response R containing tokens.
        encrypted_mapping: Encrypted mapping table M̃ (bytes).
        encryption_key: Encryption key K (bytes).

    Returns:
        ReconstructResult with clean review_text and references list.
    """
    # ───────────────────────────────────────────────────
    # Step 1: Decrypt mapping table
    # ───────────────────────────────────────────────────
    mapping_table: Dict = decrypt_mapping(encrypted_mapping, encryption_key)

    # ───────────────────────────────────────────────────
    # Step 2: Extract tokens from response
    # ───────────────────────────────────────────────────
    tokens = _extract_tokens(llm_response)

    # ───────────────────────────────────────────────────
    # Step 3: Initialize working copy
    # ───────────────────────────────────────────────────
    final_response: str = llm_response

    # ───────────────────────────────────────────────────
    # Step 4: Track references (deduplicated by name)
    # ───────────────────────────────────────────────────
    seen_names: set = set()
    references: List[Dict] = []

    # ───────────────────────────────────────────────────
    # Step 5-11: Process each token
    # ───────────────────────────────────────────────────
    for token in tokens:
        # Step 6: Skip unknown tokens
        if token not in mapping_table:
            continue

        # Step 7: Retrieve mapping entry
        entry = mapping_table[token]
        name = entry['name']
        lineno = entry['lineno']

        # Step 8: Determine the token prefix for type labeling
        prefix = token.split("_")[0] if "_" in token else "VAR"
        type_label = _PREFIX_LABELS.get(prefix, "Identifier")

        # Step 9: Replace token with just the clean name
        final_response = final_response.replace(token, name)

        # Step 10: Collect reference (deduplicated by name)
        if name not in seen_names:
            seen_names.add(name)
            references.append({
                'name': name,
                'lineno': lineno,
                'type': type_label,
                'prefix': prefix,
                'ctx': entry.get('ctx', {}),
                'occurrences': entry.get('occurrences', [{'lineno': lineno, 'col_offset': entry.get('col_offset', 0)}]),
            })

    return ReconstructResult(
        review_text=final_response,
        references=references,
    )


# ═══════════════════════════════════════════════════════════
# Private helpers
# ═══════════════════════════════════════════════════════════

def _extract_tokens(text: str) -> List[str]:
    """
    Extract all abstraction tokens from text.

    Pattern: (FUNC|VAR|SECRET|CONST|NUM|CLASS)_\\d+

    Returns a deduplicated list preserving first-occurrence order.
    """
    pattern = r'\b((?:FUNC|VAR|SECRET|CONST|NUM|CLASS)_\d+)\b'
    matches = re.findall(pattern, text)

    # Deduplicate while preserving order
    seen = set()
    unique: List[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def _format_context_blocks(references: List[Dict]) -> str:
    """
    Format context blocks for appending to translated output.

    Shows only significant identifiers (Functions, Classes, Secrets)
    with their surrounding source lines, plus a compact reference
    list for all others.

    Format example::

        ─── Source Context ────────────────────────────────
        calculate_commission (line 45):

          43 │ commission_rate = 0.029
          44 │
        → 45 │ def calculate_commission(amount):
          46 │     return amount * commission_rate
          47 │

    """
    if not references:
        return ""

    # Separate significant (show full context) from minor (compact list)
    significant_prefixes = {"FUNC", "CLASS", "SECRET"}
    significant = [r for r in references if r.get('prefix') in significant_prefixes]
    minor = [r for r in references if r.get('prefix') not in significant_prefixes]

    lines = ["─── Source References ─────────────────────────────"]

    # Full context blocks for significant identifiers
    for ref in significant:
        name = ref.get('name', '???')
        lineno = ref.get('lineno', '?')
        ctx = ref.get('ctx', {})

        lines.append(f"\n{name} (line {lineno}):\n")

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

    # Compact list for minor identifiers
    if minor:
        lines.append("\nOther referenced identifiers:\n")
        for ref in minor:
            name = ref.get('name', '???')
            lineno = ref.get('lineno', '?')
            type_label = ref.get('type', 'Identifier')
            lines.append(f"  • {name} (line {lineno}) — {type_label}")
        lines.append("")

    lines.append("───────────────────────────────────────────────────")
    return '\n'.join(lines)
