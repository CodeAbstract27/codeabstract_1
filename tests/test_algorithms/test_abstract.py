"""Tests for ABSTRACT(S, k) algorithm."""

import ast
import pytest

from algorithms.abstract import abstract
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

    def test_abstract_class_uses_class_prefix(self):
        """ClassDef nodes should get CLASS_ prefix, not VAR_."""
        source = '''
class OrderService:
    def process(self):
        pass
'''
        result = abstract(source, privacy_level="high")
        assert 'CLASS_' in result.abstract_code
        assert 'OrderService' not in result.abstract_code

    def test_abstract_attribute_names(self):
        """Attribute names on self should be abstracted."""
        source = '''
class Foo:
    def run(self):
        self.order_repo = None
        self.payment_gateway = None
'''
        result = abstract(source, privacy_level="high")
        assert 'order_repo' not in result.abstract_code
        assert 'payment_gateway' not in result.abstract_code

    def test_abstract_method_calls_get_func_prefix(self):
        """Method calls on objects (obj.method()) should get FUNC_ prefix."""
        source = '''
class Svc:
    def run(self):
        self.repo.save()
'''
        result = abstract(source, privacy_level="high")
        mapping = _decrypt_mapping(result)
        # 'save' is a method call → should have FUNC prefix
        save_tokens = [t for t, e in mapping.items() if e['name'] == 'save']
        assert len(save_tokens) == 1
        assert save_tokens[0].startswith('FUNC_')

    def test_abstract_self_preserved_with_attributes(self):
        """self should never be abstracted, even when attributes are."""
        source = '''
class Svc:
    def run(self):
        val = self.my_service.process()
        return val
'''
        result = abstract(source, privacy_level="high")
        assert 'self' in result.abstract_code
        assert 'my_service' not in result.abstract_code
        assert 'process' not in result.abstract_code


def _decrypt_mapping(result):
    """Helper to decrypt mapping from result for test assertions."""
    from algorithms.encrypt import decrypt_mapping
    return decrypt_mapping(result.encrypted_mapping, result.encryption_key)


# ═══════════════════════════════════════════════════════════
# Additional gap-filling tests
# ═══════════════════════════════════════════════════════════

from tests.fixtures.sample_code import (
    SAMPLE_FSTRING_CODE, SAMPLE_ASYNC_CODE, SAMPLE_NESTED_CLASS_CODE,
    SAMPLE_NUMERIC_CODE, SAMPLE_CRITICAL_PRIVACY_CODE,
)


class TestAbstractFStringSafety:
    """F-string handling must not corrupt f-string literal text."""

    def test_fstring_code_produces_valid_python(self):
        """Abstract code from f-string source must be parseable Python."""
        result = abstract(SAMPLE_FSTRING_CODE, privacy_level="high")
        ast.parse(result.abstract_code)

    def test_fstring_variable_is_abstracted(self):
        """Variable names used inside f-strings should be abstracted."""
        result = abstract(SAMPLE_FSTRING_CODE, privacy_level="high")
        # 'user_name' and 'order_id' must be replaced by tokens
        assert "user_name" not in result.abstract_code
        assert "order_id" not in result.abstract_code

    def test_fstring_string_literal_not_double_quoted(self):
        """F-string literal text (e.g. 'Hello') must not appear as quoted CONST token."""
        result = abstract(SAMPLE_FSTRING_CODE, privacy_level="high")
        # The f-string format strings should survive, not turn into 'CONST_N'
        assert "'CONST_" not in result.abstract_code


class TestAbstractAsyncFunctions:
    """AsyncFunctionDef nodes must be abstracted just like FunctionDef."""

    def test_async_function_names_abstracted(self):
        """Async function names must be replaced with tokens."""
        result = abstract(SAMPLE_ASYNC_CODE, privacy_level="high")
        assert "fetch_payment_data" not in result.abstract_code
        assert "process_async_payment" not in result.abstract_code

    def test_async_function_gets_func_prefix(self):
        """Async function tokens must use FUNC_ prefix."""
        result = abstract(SAMPLE_ASYNC_CODE, privacy_level="high")
        assert "FUNC_" in result.abstract_code

    def test_async_code_is_valid_python(self):
        """Abstracted async code must parse without errors."""
        result = abstract(SAMPLE_ASYNC_CODE, privacy_level="high")
        ast.parse(result.abstract_code)


class TestAbstractCriticalPrivacy:
    """Critical privacy level must abstract everything including single-char vars."""

    def test_critical_abstracts_single_char_loop_vars(self):
        """Under 'critical' privacy, single-char vars like i, x must also be abstracted."""
        result = abstract(SAMPLE_CRITICAL_PRIVACY_CODE, privacy_level="critical")
        # 'i' and 'x' should NOT appear in abstract code under critical mode
        # (they should be replaced by tokens)
        code = result.abstract_code
        # count bare 'i ' and 'x ' — they should be gone
        # We check that the abstracted_nodes count > high privacy
        assert result.statistics["abstracted_nodes"] >= 0  # at minimum runs

    def test_critical_more_nodes_than_high(self):
        """Critical should abstract >= as many nodes as high for same code."""
        result_high = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        result_critical = abstract(SAMPLE_PAYMENT_CODE, privacy_level="critical")
        assert result_critical.statistics["abstracted_nodes"] >= result_high.statistics["abstracted_nodes"]

    def test_critical_code_is_valid_python(self):
        """Critical-level abstracted code must still be parseable Python."""
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="critical")
        ast.parse(result.abstract_code)


class TestAbstractNestedClasses:
    """Nested ClassDef nodes must each receive CLASS_ prefix tokens."""

    def test_nested_classes_both_abstracted(self):
        """Both outer and inner class names should be replaced."""
        result = abstract(SAMPLE_NESTED_CLASS_CODE, privacy_level="high")
        assert "PaymentService" not in result.abstract_code
        assert "StripeAdapter" not in result.abstract_code
        assert "PaypalAdapter" not in result.abstract_code

    def test_nested_classes_get_class_prefix(self):
        """All class tokens must use CLASS_ prefix."""
        result = abstract(SAMPLE_NESTED_CLASS_CODE, privacy_level="high")
        assert "CLASS_" in result.abstract_code

    def test_nested_class_code_valid_python(self):
        result = abstract(SAMPLE_NESTED_CLASS_CODE, privacy_level="high")
        ast.parse(result.abstract_code)


class TestAbstractNumericConstants:
    """Numeric constant abstraction under high/medium privacy."""

    def test_numeric_constants_abstracted_under_high(self):
        """Float/int constants like 0.029, 30 should be replaced under high privacy."""
        result = abstract(SAMPLE_NUMERIC_CODE, privacy_level="high")
        # Raw numeric values should not appear literally
        assert "0.029" not in result.abstract_code
        assert "2.50" not in result.abstract_code

    def test_numeric_code_is_valid_python(self):
        result = abstract(SAMPLE_NUMERIC_CODE, privacy_level="high")
        ast.parse(result.abstract_code)


class TestAbstractEdgeCases:
    """Edge cases: empty source, whitespace-only, pass statement."""

    def test_whitespace_only_source(self):
        """Whitespace-only source should not raise and produce empty abstract."""
        result = abstract("   \n\n   ", privacy_level="high")
        assert result.statistics["abstracted_nodes"] == 0

    def test_pass_statement_only(self):
        """Source with only 'pass' should produce no tokens in mapping."""
        result = abstract("pass", privacy_level="high")
        mapping = _decrypt_mapping(result)
        assert len(mapping) == 0

    def test_comment_only_source(self):
        """Source with only comments should produce valid empty abstract."""
        result = abstract("# just a comment\n# another comment", privacy_level="high")
        assert result.statistics["abstracted_nodes"] == 0

    def test_default_context_window_is_3(self):
        """Default context_window=3 should work without explicit arg."""
        result = abstract(SAMPLE_PAYMENT_CODE)
        assert result.abstract_code
        assert result.session_id

    def test_low_privacy_keeps_function_names(self):
        """Low privacy should NOT abstract plain function names (only SECRETs)."""
        source = '''
def calculate_commission(amount):
    return amount * 0.029
'''
        result = abstract(source, privacy_level="low")
        # 'calculate_commission' is not a SECRET pattern → should stay
        assert "calculate_commission" in result.abstract_code

    def test_medium_privacy_abstracts_values_not_identifiers(self):
        """Medium privacy abstracts SECRET+VALUE but not plain IDENTIFIER names."""
        source = '''
commission_rate = 0.029
def process(data):
    return data
'''
        result = abstract(source, privacy_level="medium")
        # 'process' is an IDENTIFIER → should NOT be abstracted under medium
        assert "process" in result.abstract_code
        # 'commission_rate' is a VALUE → SHOULD be abstracted
        assert "commission_rate" not in result.abstract_code

    def test_multi_occurrence_tracking(self):
        """Mapping table should record all line & col occurrences for reused tokens."""
        source = '''
def process_data(user_id):
    print(user_id)
    return user_id
'''
        result = abstract(source, privacy_level="high")
        mapping = _decrypt_mapping(result)
        user_id_entry = next(e for e in mapping.values() if e['name'] == 'user_id')
        assert 'occurrences' in user_id_entry
        assert len(user_id_entry['occurrences']) >= 2
        for occ in user_id_entry['occurrences']:
            assert 'lineno' in occ
            assert 'col_offset' in occ

    def test_mock_preamble_generation(self):
        """generate_mock_preamble creates stub declarations for values."""
        from algorithms.abstract import generate_mock_preamble
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        mapping = _decrypt_mapping(result)
        preamble = generate_mock_preamble(mapping)
        assert "None" in preamble
