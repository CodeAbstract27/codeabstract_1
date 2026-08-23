"""
Context Extraction Implementation

Implements GetContext(S, lineno, k) helper algorithm.
Extracts ±k lines of source code surrounding a target line number.
"""
"Extratrig  method"
from typing import Dict, List, Optional


def get_context(
    source_code: str,
    line_number: int,
    window_size: int = 3,
    lines: Optional[List[str]] = None,
) -> Dict:
    """
    GetContext(S, lineno, k) — Extract surrounding code context.

    Args:
        source_code: Full source code string S. Ignored for the split
            when *lines* is given -- see below.
        line_number: Target line number (1-indexed).
        window_size: Context window size k (±k lines).
        lines: Pre-split ``source_code.split('\\n')``, for a caller that
            requests context for many line numbers against the same
            source. ABSTRACT calls this once per mapped identifier, so
            re-splitting the whole file inside every call made context
            extraction the dominant cost on large files -- O(identifiers
            x file size) instead of O(file size). Splitting once and
            passing the result through removes that; the single-call
            default (split *source_code* here) is unchanged for every
            other caller.

    Returns:
        Context dictionary with keys:
        - snippet: String of extracted lines.
        - start_line: Starting line number of the window.
        - end_line: Ending line number of the window.
        - target_line: The target line number.

    Implements:
        GetContext helper from formal specification.
    """
    if lines is None:
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
