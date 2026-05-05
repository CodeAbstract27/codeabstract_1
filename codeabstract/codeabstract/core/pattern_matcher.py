"""
Pattern Matcher

Provides regex-based pattern matching utilities for the
CLASSIFY algorithm's sensitivity detection.
"""

import re
from typing import List


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
        try:
            if re.search(pattern, text):
                return pattern
        except re.error:
            continue
    return ""
