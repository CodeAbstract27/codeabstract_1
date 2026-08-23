"""
Unit tests for core/pattern_matcher.py

Tests regex pattern matching functions matches_any and find_matching_pattern.
"""

from core.pattern_matcher import matches_any, find_matching_pattern
from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS


def test_matches_any_secrets():
    """TC-PM-01: Sensitive pattern names should return True."""
    assert matches_any("stripe_api_key", SECRET_PATTERNS) is True
    assert matches_any("db_password", SECRET_PATTERNS) is True
    assert matches_any("auth_token", SECRET_PATTERNS) is True
    assert matches_any("bearer_token", SECRET_PATTERNS) is True


def test_matches_any_values():
    """Business value patterns should match correctly."""
    assert matches_any("commission_rate", VALUE_PATTERNS) is True
    assert matches_any("total_amount", VALUE_PATTERNS) is True
    assert matches_any("api_endpoint", VALUE_PATTERNS) is True


def test_matches_any_no_match():
    """TC-PM-02: Non-sensitive identifiers should return False."""
    assert matches_any("calculate_sum", SECRET_PATTERNS) is False
    assert matches_any("item_index", SECRET_PATTERNS) is False
    assert matches_any("user_name", SECRET_PATTERNS) is False


def test_find_matching_pattern():
    """TC-PM-03: Should return the exact regex pattern string that matched."""
    matched_pattern = find_matching_pattern("db_password", SECRET_PATTERNS)
    assert matched_pattern != ""
    assert "password" in matched_pattern


def test_find_matching_pattern_none():
    """Should return empty string if no pattern matches."""
    assert find_matching_pattern("generic_variable", SECRET_PATTERNS) == ""


def test_pattern_matcher_handles_malformed_regex():
    """Malformed regex strings in list should be safely skipped."""
    bad_patterns = ["[invalid_regex(", r".*key.*"]
    assert matches_any("api_key", bad_patterns) is True
    assert find_matching_pattern("api_key", bad_patterns) == r".*key.*"
