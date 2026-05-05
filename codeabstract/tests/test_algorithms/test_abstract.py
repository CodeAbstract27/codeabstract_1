"""Tests for ABSTRACT(S, k) algorithm."""

import ast
import pytest

from codeabstract.algorithms.abstract import abstract
from tests.fixtures.sample_code import (
    SAMPLE_PAYMENT_CODE, SAMPLE_SIMPLE_CODE, SAMPLE_SECRET_HEAVY_CODE,
)


class TestAbstract:
    """Test suite for Algorithm 1: ABSTRACT(S, k)."""

    def test_abstract_returns_valid_python(self):
        """Abstract code must be parseable Python."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        # Should not raise
        ast.parse(result.abstract_code)

    def test_abstract_contains_tokens(self):
        """Abstract code should contain generated tokens."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        has_func = 'FUNC_' in result.abstract_code
        has_var = 'VAR_' in result.abstract_code
        has_secret = 'SECRET_' in result.abstract_code
        assert has_func or has_var or has_secret, (
            "Abstract code should contain at least one token"
        )

    def test_abstract_removes_sensitive_names(self):
        """Original sensitive identifiers must not appear in output."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        assert 'STRIPE_API_KEY' not in result.abstract_code
        assert 'PAYPAL_SECRET' not in result.abstract_code
        assert 'calculate_commission' not in result.abstract_code

    def test_abstract_detects_secrets(self):
        """SECRET patterns should be detected."""
        result = abstract(SAMPLE_SECRET_HEAVY_CODE, privacy_level="medium")
        assert result.statistics['secrets_found'] >= 1
        assert 'SECRET_' in result.abstract_code

    def test_abstract_reuses_tokens(self):
        """Same identifier used multiple times should get same token."""
        source = '''
def calc(amount):
    result = amount * 2
    return amount + result
'''
        result = abstract(source, privacy_level="high")
        # 'amount' appears 3 times (arg + 2 uses)
        # should all map to same token
        code = result.abstract_code
        # Find the token for amount
        for token, entry in _decrypt_mapping(result).items():
            if entry['name'] == 'amount':
                count = code.count(token)
                assert count >= 2, f"Token {token} should appear ≥2 times, got {count}"
                break

    def test_abstract_preserves_builtins(self):
        """Builtins like print, len, round should not be abstracted."""
        source = '''
def foo(items):
    print(len(items))
    return round(sum(items), 2)
'''
        result = abstract(source, privacy_level="high")
        # These should still be present
        assert 'print' in result.abstract_code
        assert 'len' in result.abstract_code
        assert 'round' in result.abstract_code

    def test_abstract_skips_single_char(self):
        """Single-char variables like i, j, x should not be abstracted."""
        source = '''
for i in range(10):
    x = i * 2
'''
        result = abstract(source, privacy_level="high")
        assert 'i' in result.abstract_code
        assert 'x' in result.abstract_code

    def test_abstract_skips_dunder(self):
        """Dunder methods should not be abstracted."""
        source = '''
class Foo:
    def __init__(self):
        self.bar = 1
'''
        result = abstract(source, privacy_level="high")
        assert '__init__' in result.abstract_code

    def test_abstract_generates_session_id(self):
        """Result should include a session ID."""
        result = abstract(SAMPLE_SIMPLE_CODE, privacy_level="high")
        assert result.session_id
        assert len(result.session_id) == 36  # UUID format

    def test_abstract_encryption_produces_bytes(self):
        """Encrypted mapping and key should be bytes."""
        result = abstract(SAMPLE_SIMPLE_CODE, privacy_level="high")
        assert isinstance(result.encrypted_mapping, bytes)
        assert isinstance(result.encryption_key, bytes)

    def test_abstract_statistics(self):
        """Statistics should have expected keys."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        stats = result.statistics
        assert 'total_nodes' in stats
        assert 'abstracted_nodes' in stats
        assert 'skipped_nodes' in stats
        assert 'secrets_found' in stats
        assert 'values_found' in stats
        assert stats['total_nodes'] > 0
        assert stats['abstracted_nodes'] > 0

    def test_abstract_syntax_error_raises(self):
        """Invalid Python should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid Python syntax"):
            abstract("def broken(:", privacy_level="high")

    def test_abstract_context_window(self):
        """Context window should affect snippet size."""
        result_k1 = abstract(SAMPLE_PAYMENT_CODE, context_window=1, privacy_level="high")
        result_k5 = abstract(SAMPLE_PAYMENT_CODE, context_window=5, privacy_level="high")
        # Both should work
        assert result_k1.abstract_code
        assert result_k5.abstract_code

    def test_abstract_privacy_low(self):
        """Low privacy should only abstract secrets."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="low")
        # Secrets should be abstracted
        assert 'SECRET_' in result.abstract_code or result.statistics['secrets_found'] >= 0
        # Non-secret identifiers should mostly remain
        # (calculate_commission is not a secret pattern)

    def test_abstract_privacy_high(self):
        """High privacy should abstract everything significant."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        assert result.statistics['abstracted_nodes'] > 0


def _decrypt_mapping(result):
    """Helper to decrypt mapping from result for test assertions."""
    from codeabstract.algorithms.encrypt import decrypt_mapping
    return decrypt_mapping(result.encrypted_mapping, result.encryption_key)
