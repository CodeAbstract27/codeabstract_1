"""
RECONSTRUCT(R, M̃, K) Algorithm Implementation

Implements formal Algorithm 3 from specification.

Translates abstract LLM responses back to human-readable feedback
by replacing tokens with original identifiers and appending
formatted source context blocks.
"""

import re
from typing import Dict, List

from algorithms.encrypt import decrypt_mapping


def reconstruct(
    llm_response: str,
    encrypted_mapping: bytes,
    encryption_key: bytes,
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
    # Step 2: Extract tokens from response
    # ───────────────────────────────────────────────────
    tokens = _extract_tokens(llm_response)

    # ───────────────────────────────────────────────────
    # Step 3: Initialize working copy
    # ───────────────────────────────────────────────────
    final_response: str = llm_response

    # ───────────────────────────────────────────────────
    # Step 4: Initialize context blocks
    # ───────────────────────────────────────────────────
    context_blocks: List[Dict] = []

    # ───────────────────────────────────────────────────
    # Step 5-11: Process each token
    # ───────────────────────────────────────────────────
    for token in tokens:
        # Step 6: Skip unknown tokens
        if token not in mapping_table:
            continue

        # Step 7: Retrieve mapping entry
        entry = mapping_table[token]

        # Step 8: Create human-readable reference
        reference = f"{entry['name']} (line {entry['lineno']})"

        # Step 9: Replace all occurrences of token with reference
        final_response = final_response.replace(token, reference)

        # Step 10: Collect context block
        context_blocks.append({
            'name': entry['name'],
            'lineno': entry['lineno'],
            'ctx': entry.get('ctx', {}),
        })

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

def _extract_tokens(text: str) -> List[str]:
    """
    Extract all abstraction tokens from text.

    Pattern: (FUNC|VAR|SECRET|CONST)_\\d+

    Returns a deduplicated list preserving first-occurrence order.
    """
    pattern = r'\b((?:FUNC|VAR|SECRET|CONST)_\d+)\b'
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

    lines.append("───────────────────────────────────────────────────")
    return '\n'.join(lines)
