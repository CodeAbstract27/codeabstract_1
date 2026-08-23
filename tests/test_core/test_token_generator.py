"""
Tests for core/token_generator.py

Covers:
- Sequential token generation per prefix
- Independent counters per prefix
- Auto-initialization of unknown prefixes
- get_counts() returns a copy
- Custom starting counters
"""

import pytest

from core.token_generator import TokenGenerator


class TestTokenGenerator:
    """Test suite for TokenGenerator."""

    # ─── Basic generation ──────────────────────────────────

    def test_first_token_is_zero(self):
        """First generated token for any prefix must be PREFIX_0."""
        gen = TokenGenerator()
        assert gen.generate("FUNC") == "FUNC_0"
        assert gen.generate("VAR") == "VAR_0"
        assert gen.generate("SECRET") == "SECRET_0"
        assert gen.generate("CONST") == "CONST_0"
        assert gen.generate("CLASS") == "CLASS_0"

    def test_sequential_tokens(self):
        """Repeated calls on the same prefix must increment counter."""
        gen = TokenGenerator()
        assert gen.generate("FUNC") == "FUNC_0"
        assert gen.generate("FUNC") == "FUNC_1"
        assert gen.generate("FUNC") == "FUNC_2"

    def test_large_counter(self):
        """Counter should keep incrementing without limit."""
        gen = TokenGenerator()
        for _ in range(99):
            gen.generate("VAR")
        assert gen.generate("VAR") == "VAR_99"

    # ─── Prefix independence ────────────────────────────────

    def test_counters_are_independent(self):
        """Incrementing FUNC counter must not affect VAR counter."""
        gen = TokenGenerator()
        gen.generate("FUNC")
        gen.generate("FUNC")
        gen.generate("FUNC")
        # VAR counter should still start at 0
        assert gen.generate("VAR") == "VAR_0"

    def test_all_prefixes_independent(self):
        """All five standard prefixes count independently."""
        gen = TokenGenerator()
        for prefix in ("FUNC", "VAR", "SECRET", "CONST", "CLASS"):
            assert gen.generate(prefix) == f"{prefix}_0"
            assert gen.generate(prefix) == f"{prefix}_1"

    # ─── Auto-initialization ────────────────────────────────

    def test_new_prefix_auto_initializes(self):
        """An unknown prefix must auto-initialize to 0."""
        gen = TokenGenerator()
        assert gen.generate("CUSTOM") == "CUSTOM_0"
        assert gen.generate("CUSTOM") == "CUSTOM_1"

    def test_new_prefix_independent_of_others(self):
        """Auto-initialized prefix counter is independent."""
        gen = TokenGenerator()
        gen.generate("FUNC")
        gen.generate("FUNC")
        gen.generate("NEWPREFIX")
        assert gen.generate("NEWPREFIX") == "NEWPREFIX_1"

    # ─── Custom starting counters ───────────────────────────

    def test_custom_starting_counter(self):
        """Custom starting counter dict must be respected."""
        gen = TokenGenerator(counters={"FUNC": 5, "VAR": 10})
        assert gen.generate("FUNC") == "FUNC_5"
        assert gen.generate("FUNC") == "FUNC_6"
        assert gen.generate("VAR") == "VAR_10"

    def test_none_counters_uses_defaults(self):
        """Passing None for counters should use default all-zero counters."""
        gen = TokenGenerator(counters=None)
        assert gen.generate("FUNC") == "FUNC_0"
        assert gen.generate("SECRET") == "SECRET_0"

    def test_empty_counters_dict(self):
        """Empty dict as counters should auto-init all prefixes."""
        gen = TokenGenerator(counters={})
        assert gen.generate("FUNC") == "FUNC_0"
        assert gen.generate("VAR") == "VAR_0"

    # ─── get_counts() ───────────────────────────────────────

    def test_get_counts_returns_correct_values(self):
        """get_counts() must reflect the current counter values."""
        gen = TokenGenerator()
        gen.generate("FUNC")
        gen.generate("FUNC")
        gen.generate("VAR")
        counts = gen.get_counts()
        assert counts["FUNC"] == 2
        assert counts["VAR"] == 1

    def test_get_counts_returns_copy(self):
        """Mutating the returned dict must NOT affect the generator's state."""
        gen = TokenGenerator()
        gen.generate("FUNC")
        counts = gen.get_counts()
        counts["FUNC"] = 9999  # mutate the copy
        # Internal counter should still be 1
        next_token = gen.generate("FUNC")
        assert next_token == "FUNC_1"

    def test_get_counts_initial_state(self):
        """Freshly constructed generator should have all counters at 0."""
        gen = TokenGenerator()
        counts = gen.get_counts()
        for prefix in ("FUNC", "VAR", "SECRET", "CONST", "CLASS"):
            assert counts[prefix] == 0

    # ─── Token format ───────────────────────────────────────

    def test_token_format_is_prefix_underscore_number(self):
        """Token must strictly follow PREFIX_N format."""
        gen = TokenGenerator()
        token = gen.generate("FUNC")
        parts = token.split("_")
        assert len(parts) == 2
        assert parts[0] == "FUNC"
        assert parts[1].isdigit()
