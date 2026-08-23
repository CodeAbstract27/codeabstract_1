"""
Regression: ``core.pattern_matcher`` must not be quadratic in input length.

Found by direct fuzzing, not by inspection: ``abstract()`` hung
indefinitely (still running after 15s, killed) on a source file containing
a single large string literal -- something ordinary, not adversarial: an
embedded base64 blob, a long SQL string, a big JSON/config literal.

Root cause: almost every entry in ``config.patterns.SECRET_PATTERNS`` /
``VALUE_PATTERNS`` is the unanchored ``.*word.*`` idiom, matched via
``re.search``. Against a *non-matching* string, an unanchored ``.*X.*``
is O(n^2) in the length of the text -- ``search()`` retries the pattern
at every start position, and at each one the greedy ``.*`` backtracks
character by character before giving up. With ~40 such patterns applied
to every literal-bearing AST node (``classify_signals``'s Tier 3 / Tier 4b
name-pattern checks), a single large literal made this the dominant cost
by a wide margin.

Measured before the fix (``core/pattern_matcher.py``, pre-fix):
n=2,000 chars: 0.046s; n=4,000: 0.197s; n=8,000: 0.736s (already ~O(n^2));
n=200,000: did not complete within 15s.

Measured after: n=8,000: 0.005s; n=200,000: 0.072s; n=1,000,000: 0.34s --
consistent with the intended O(n) behaviour of a real substring check.

The fix (recognising the ".*word.*" idiom as a plain substring check) is
a semantic no-op for that idiom specifically -- unanchored ``.*`` on both
sides means "matches if the literal appears anywhere", which is exactly
what `in` checks, and re.search's "try every start position" behaviour
means this holds for multi-line text too (a `.*` never needs to span a
newline to find a later match, since search can start immediately after
it). The five genuinely regex-shaped patterns (vendor key formats,
``(^|_)pass(_|$)``, etc.) are unaffected -- they don't match the idiom
and fall through to the original ``re.search`` path unchanged.
"""

import time

import pytest

import config.patterns as patterns
from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping
from core.pattern_matcher import find_matching_pattern, matches_any


class TestPatternMatcherIsLinearNotQuadratic:

    def test_large_non_matching_literal_classifies_quickly(self):
        """
        The actual reproduction: a single large string literal must not
        make abstraction hang. Generous bound (2s) well above the ~0.07s
        measured during development, to absorb slower CI hardware without
        making this test a timing hair-trigger -- the property under test
        is "not quadratic", not "exactly this fast".
        """
        source = 'x = "' + ('a' * 200_000) + '"\n'
        start = time.perf_counter()
        abstract(source)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, (
            f"abstract() took {elapsed:.2f}s on a 200,000-char literal -- "
            f"looks like the O(n^2) pattern-matching regression is back"
        )

    def test_scaling_is_not_quadratic(self):
        """
        Doubling the input should roughly double the time, not
        quadruple it. Uses matches_any directly against the real pattern
        lists to isolate the mechanism from the rest of the pipeline.
        """
        text_small = "b" * 20_000
        text_large = "b" * 160_000  # 8x

        def timed(text):
            start = time.perf_counter()
            for _ in range(5):
                matches_any(text, patterns.SECRET_PATTERNS)
                matches_any(text, patterns.VALUE_PATTERNS)
            return time.perf_counter() - start

        small_time = timed(text_small)
        large_time = timed(text_large)

        # O(n) predicts ~8x; O(n^2) predicts ~64x. Generous margin (20x)
        # to stay robust to measurement noise while still catching a
        # regression back to quadratic behaviour.
        assert large_time < small_time * 20, (
            f"8x input took {large_time / small_time:.1f}x longer -- "
            f"expected roughly linear scaling"
        )


class TestPatternMatcherCorrectnessPreserved:
    """The performance fix must not change what matches."""

    @pytest.mark.parametrize("word,pattern_list", [
        ("key", patterns.SECRET_PATTERNS),
        ("password", patterns.SECRET_PATTERNS),
        ("api_key", patterns.SECRET_PATTERNS),
        ("url", patterns.VALUE_PATTERNS),
        ("commission", patterns.VALUE_PATTERNS),
    ])
    def test_substring_still_matches_when_embedded(self, word, pattern_list):
        assert matches_any(f"some_{word}_field", pattern_list)
        assert matches_any(f"{word}", pattern_list)
        assert matches_any(f"prefix{word}suffix", pattern_list)

    def test_non_matching_text_still_does_not_match(self):
        assert not matches_any("ordinary_identifier_name", patterns.SECRET_PATTERNS)
        assert not matches_any("ordinary_identifier_name", patterns.VALUE_PATTERNS)

    def test_multiline_text_still_matches(self):
        """
        A `.*word.*` idiom's `.*` doesn't span a newline, but re.search
        tries every start position -- so a match after a newline was
        always found, and must still be.
        """
        assert matches_any("first line\nsecond_line_has_a_password", patterns.SECRET_PATTERNS)

    def test_genuinely_regex_patterns_are_unaffected(self):
        """
        The vendor-format and word-boundary patterns don't match the
        bare-substring idiom and must still run as real regex.
        """
        assert matches_any("sk-" + "a" * 40, patterns.SECRET_PATTERNS)
        assert not matches_any("sk-tooshort", patterns.SECRET_PATTERNS)
        assert matches_any("db_pass", patterns.SECRET_PATTERNS)
        assert matches_any("user_pwd", patterns.SECRET_PATTERNS)
        # The word-boundary anchoring's whole point (Phase 0 / D1 comment
        # in config/patterns.py): substrings that merely contain "pass"
        # must not classify as SECRET.
        assert not matches_any("bypass", patterns.SECRET_PATTERNS)
        assert not matches_any("compass", patterns.SECRET_PATTERNS)
        assert not matches_any("passenger", patterns.SECRET_PATTERNS)

    def test_find_matching_pattern_returns_the_same_pattern_string(self):
        """
        find_matching_pattern's contract is to return the original
        pattern string (used elsewhere for logging/debugging) -- the
        substring fast path must still return the *pattern*, not the
        literal it extracted.
        """
        found = find_matching_pattern("my_api_key_value", patterns.SECRET_PATTERNS)
        assert found == ".*key.*" or found == ".*api_key.*"
        assert found in patterns.SECRET_PATTERNS

    def test_end_to_end_classification_unchanged_for_a_real_case(self):
        """
        One full-pipeline check that the rewrite didn't change a real
        classification decision, not just the matcher in isolation.
        """
        source = 'api_key = "sk-" + "x" * 40\ntimeout_seconds = 30\n'
        result = abstract(source, privacy_level="medium")
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
        mapping_names = {entry["name"] for entry in mapping.values()}
        assert "api_key" in mapping_names
        assert "timeout_seconds" in mapping_names
