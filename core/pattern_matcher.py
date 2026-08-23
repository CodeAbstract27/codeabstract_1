"""
Pattern Matcher

Provides regex-based pattern matching utilities for the
CLASSIFY algorithm's sensitivity detection.
"""

import re
from typing import List, Optional

# Almost every entry in config.patterns.SECRET_PATTERNS/VALUE_PATTERNS is
# the unanchored ".*word.*" idiom -- "does this text contain 'word'
# anywhere". Matched via re.search, an unanchored ".*X.*" against a
# *non-matching* string is O(n^2) in the length of the text: search()
# retries the pattern at every start position, and at each one the
# greedy ".*" backtracks character by character looking for "X" before
# giving up. With ~40 such patterns applied to every literal-bearing AST
# node, a single large string literal made classification hang --
# measured: 0.055s at 2,000 chars, 0.735s at 8,000 (already ~O(n^2) per
# pattern), and unrecoverable within 15s at 200,000 chars, which is not
# an exotic input: an embedded base64 blob, a long SQL string, or a
# large JSON/config literal are all ordinary Python source.
#
# ".*word.*" with no other regex metacharacters in "word" is exactly
# `"word" in text` -- unanchored `.*` on both sides means "anywhere",
# and a plain literal has no regex semantics to preserve. This matches
# that idiom precisely (rejecting anything with the metacharacters that
# would change its meaning under `in`) and falls back to real regex
# matching for every pattern that doesn't fit it, so behaviour for the
# genuinely regex-shaped patterns (vendor key formats, `(^|_)pass(_|$)`,
# etc.) is completely unchanged.
_BARE_SUBSTRING_IDIOM = re.compile(r'^\.\*([^.^$+?*\[\]{}()|\\]+)\.\*$')


def _as_plain_substring(pattern: str) -> Optional[str]:
    """Return the literal *pattern* is checking for, or None if it needs real regex."""
    match = _BARE_SUBSTRING_IDIOM.match(pattern)
    return match.group(1) if match else None


def matches_any(text: str, patterns: List[str]) -> bool:
    """
    Check if text matches any pattern in the provided list.

    Args:
        text: Input text to check (should be lowercased by caller).
        patterns: List of regex pattern strings.

    Returns:
        True if any pattern matches, False otherwise.
    """
    for pattern in patterns:
        literal = _as_plain_substring(pattern)
        if literal is not None:
            if literal in text:
                return True
            continue
        try:
            if re.search(pattern, text):
                return True
        except re.error:
            # Skip malformed patterns
            continue
    return False


def find_matching_pattern(text: str, patterns: List[str]) -> str:
    """
    Find the first matching pattern from the list.

    Args:
        text: Input text to check.
        patterns: List of regex pattern strings.

    Returns:
        The first matching pattern string, or empty string if none match.
    """
    for pattern in patterns:
        literal = _as_plain_substring(pattern)
        if literal is not None:
            if literal in text:
                return pattern
            continue
        try:
            if re.search(pattern, text):
                return pattern
        except re.error:
            continue
    return ""
