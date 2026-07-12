"""
Context Extraction Implementation

Implements GetContext(S, lineno, k) helper algorithm.
Extracts ±k lines of source code surrounding a target line number.
"""
"Extratrig  method"
from typing import Dict


def get_context(
    source_code: str,
    line_number: int,
    window_size: int = 3
) -> Dict:
    """
    GetContext(S, lineno, k) — Extract surrounding code context.

    Args:
        source_code: Full source code string S.
        line_number: Target line number (1-indexed).
        window_size: Context window size k (±k lines).

    Returns:
        Context dictionary with keys:
        - snippet: String of extracted lines.
        - start_line: Starting line number of the window.
        - end_line: Ending line number of the window.
        - target_line: The target line number.

    Implements:
        GetContext helper from formal specification.
    """
    # Split source into individual lines
    lines = source_code.split('\n')
    total_lines = len(lines)

    # Calculate window bounds (1-indexed)
    start_line = max(1, line_number - window_size)
    end_line = min(total_lines, line_number + window_size)

    # Extract snippet (convert to 0-indexed for slicing)
    snippet_lines = lines[start_line - 1: end_line]
    snippet = '\n'.join(snippet_lines)

    return {
        'snippet': snippet,
        'start_line': start_line,
        'end_line': end_line,
        'target_line': line_number,
    }
