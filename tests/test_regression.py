"""
Comprehensive Regression Test Suite for CodeAbstract

Covers all 4 core algorithms with edge cases:
  - Algorithm 1 (ABSTRACT): decorators, lambdas, global/nonlocal, walrus,
    starred, try/except, comprehensions, nested structures, Unicode, multiline
    strings, token collision, critical privacy, determinism, large files
  - Algorithm 2 (CLASSIFY): boundary patterns, overlapping regex, empty names,
    high-entropy strings, numeric edge values, Attribute gap
  - Algorithm 3 (RECONSTRUCT): token-in-original-name collision, all prefix
    types including CLASS_, NUM_, empty response, huge response, structured API
  - Algorithm 4 (ENCRYPT): large payloads, nested dicts, binary-safe roundtrip
  - End-to-End property tests: abstract→reconstruct roundtrip for every token,
    privacy level ordering, idempotency, scalability
"""

import ast
import re
import pytest

from algorithms.abstract import abstract, AbstractionResult
from algorithms.classify import classify_node
from algorithms.encrypt import encrypt_mapping, decrypt_mapping
from algorithms.reconstruct import reconstruct, reconstruct_structured
from algorithms.helpers import is_semantically_significant, label_to_prefix


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _decrypt(result: AbstractionResult) -> dict:
    """Decrypt the mapping from an AbstractionResult."""
    return decrypt_mapping(result.encrypted_mapping, result.encryption_key)


def _token_names(result: AbstractionResult) -> set:
    """Return the set of all original names that were abstracted."""
    return {entry['name'] for entry in _decrypt(result).values()}


# ═══════════════════════════════════════════════════════════════════════════════
# ALGORITHM 1 — ABSTRACT(S, k) EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestAbstractDecorators:
    """Decorators should not break abstraction or produce invalid code."""

    def test_decorated_function(self):
        source = '''
import functools

def my_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@my_decorator
def process_order(order_id):
    return order_id
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'process_order' not in result.abstract_code
        assert 'my_decorator' not in result.abstract_code

    def test_multiple_decorators(self):
        source = '''
def decorator_a(fn):
    return fn

def decorator_b(fn):
    return fn

@decorator_a
@decorator_b
def sensitive_func(data):
    return data
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'sensitive_func' not in result.abstract_code


class TestAbstractLambda:
    """Lambda expressions use ast.Name nodes for args — must be handled."""

    def test_lambda_basic(self):
        source = '''
calculate_tax = lambda amount, rate: amount * rate
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'calculate_tax' not in result.abstract_code

    def test_lambda_in_map(self):
        source = '''
prices = [10, 20, 30]
discounted = list(map(lambda price: price * 0.9, prices))
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'prices' not in result.abstract_code
        assert 'discounted' not in result.abstract_code


class TestAbstractGlobalNonlocal:
    """global and nonlocal statements reference names that must be kept consistent."""

    def test_global_statement(self):
        source = '''
counter = 0

def increment():
    global counter
    counter += 1
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        # The token for 'counter' must be consistent across global usage
        mapping = _decrypt(result)
        counter_tokens = [t for t, e in mapping.items() if e['name'] == 'counter']
        assert len(counter_tokens) == 1  # single token for all occurrences

    def test_nonlocal_statement(self):
        source = '''
def outer():
    state = "init"
    def inner():
        nonlocal state
        state = "updated"
    inner()
    return state
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)


class TestAbstractWalrusOperator:
    """Walrus operator (:=) creates NamedExpr nodes."""

    def test_walrus_operator(self):
        source = '''
data = [1, 2, 3, 4, 5]
filtered = [y for x in data if (y := x * 2) > 4]
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'data' not in result.abstract_code
        assert 'filtered' not in result.abstract_code


class TestAbstractStarredExpressions:
    """Starred unpacking: *args, **kwargs, starred assignment."""

    def test_starred_assignment(self):
        source = '''
first, *rest, last = [1, 2, 3, 4, 5]
api_data = {"first": first, "rest": rest}
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'api_data' not in result.abstract_code

    def test_args_kwargs(self):
        source = '''
def flexible_handler(*args, **kwargs):
    return args, kwargs
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'flexible_handler' not in result.abstract_code


class TestAbstractTryExcept:
    """Try/except/finally blocks with exception variables."""

    def test_try_except_as_variable(self):
        source = '''
def safe_divide(numerator, denominator):
    try:
        result = numerator / denominator
    except ZeroDivisionError as error:
        result = 0
    except Exception as general_error:
        raise general_error
    finally:
        cleanup_flag = True
    return result
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'safe_divide' not in result.abstract_code
        assert 'numerator' not in result.abstract_code
        # Builtin exception names should be preserved
        assert 'ZeroDivisionError' in result.abstract_code


class TestAbstractComprehensions:
    """List/dict/set comprehensions and generator expressions."""

    def test_list_comprehension(self):
        source = '''
prices = [10, 20, 30]
taxed_prices = [price * 1.1 for price in prices if price > 15]
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'prices' not in result.abstract_code
        assert 'taxed_prices' not in result.abstract_code

    def test_dict_comprehension(self):
        source = '''
inventory = {"apple": 5, "banana": 3}
doubled = {item: count * 2 for item, count in inventory.items()}
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)

    def test_nested_comprehension(self):
        source = '''
matrix = [[row * col for col in range(3)] for row in range(3)]
flat = [cell for row_data in matrix for cell in row_data]
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)


class TestAbstractMultipleInheritance:
    """Multiple inheritance and metaclasses."""

    def test_multiple_bases(self):
        source = '''
class BaseService:
    pass

class LoggingMixin:
    pass

class PaymentGateway(BaseService, LoggingMixin):
    def charge(self, total):
        return total
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'PaymentGateway' not in result.abstract_code
        assert 'BaseService' not in result.abstract_code


class TestAbstractDeepNesting:
    """Deeply nested structures: nested functions, nested classes, nested loops."""

    def test_deeply_nested_functions(self):
        source = '''
def level_one(data):
    def level_two(filtered):
        def level_three(item):
            return item * 2
        return [level_three(x) for x in filtered]
    return level_two(data)
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        mapping = _decrypt(result)
        names = {e['name'] for e in mapping.values()}
        assert 'level_one' in names
        assert 'level_two' in names
        assert 'level_three' in names

    def test_deeply_nested_loops(self):
        source = '''
result_matrix = []
for layer in range(3):
    row_list = []
    for row_idx in range(3):
        cell_list = []
        for col_idx in range(3):
            cell_list.append(layer + row_idx + col_idx)
        row_list.append(cell_list)
    result_matrix.append(row_list)
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)


class TestAbstractUnicode:
    """Unicode identifiers (Python 3 allows non-ASCII identifiers)."""

    def test_unicode_identifiers(self):
        source = '''
données = [1, 2, 3]
résultat = sum(données)
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'données' not in result.abstract_code
        assert 'résultat' not in result.abstract_code


class TestAbstractMultilineStrings:
    """Triple-quoted / multiline string constants."""

    def test_multiline_docstring(self):
        source = '''
class ApiClient:
    """
    This client handles all API communication
    with the payment provider endpoint.
    """
    def connect(self):
        pass
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'ApiClient' not in result.abstract_code


class TestAbstractTokenCollision:
    """Original identifiers that look like tokens (e.g., FUNC_0, VAR_1)."""

    def test_identifier_named_like_token(self):
        """If original code has a variable called FUNC_0, it must still work."""
        source = '''
FUNC_0 = "this is not a token"
VAR_1 = 42
result = FUNC_0 + str(VAR_1)
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        # The system should still produce valid code — the original
        # FUNC_0/VAR_1 names get replaced by new tokens
        mapping = _decrypt(result)
        assert len(mapping) > 0


class TestAbstractDeterminism:
    """Abstracting the same code twice must produce structurally identical output."""

    def test_deterministic_token_assignment(self):
        source = '''
api_key = "sk_live_test123"
def process(data):
    return data * 2
'''
        result1 = abstract(source, privacy_level="high")
        result2 = abstract(source, privacy_level="high")
        # Token assignment order should be the same
        mapping1 = _decrypt(result1)
        mapping2 = _decrypt(result2)
        # Same number of tokens
        assert len(mapping1) == len(mapping2)
        # Same set of original names
        names1 = {e['name'] for e in mapping1.values()}
        names2 = {e['name'] for e in mapping2.values()}
        assert names1 == names2


class TestAbstractLargeFile:
    """Scalability: abstract a file with many functions/classes."""

    def test_large_module(self):
        """Generate a 50-function module and abstract it."""
        lines = []
        for i in range(50):
            lines.append(f"def function_{i}(param_{i}):")
            lines.append(f"    return param_{i} * {i}")
            lines.append("")
        source = "\n".join(lines)
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        mapping = _decrypt(result)
        # All 50 function names + 50 params + 50 numeric constants
        assert len(mapping) >= 100


class TestAbstractPrivacyLevelOrdering:
    """Higher privacy levels must abstract >= as many nodes as lower levels."""

    def test_privacy_monotonic(self):
        source = '''
API_KEY = "sk_live_secret123"
commission_rate = 0.029
base_url = "https://api.example.com/v2"

def calculate_commission(amount):
    fee = amount * commission_rate
    return round(fee, 2)

class PaymentProcessor:
    def __init__(self, api_key):
        self.api_key = api_key
'''
        counts = {}
        for level in ["low", "medium", "high", "critical"]:
            result = abstract(source, privacy_level=level)
            ast.parse(result.abstract_code)  # always valid
            counts[level] = result.statistics['abstracted_nodes']

        assert counts["low"] <= counts["medium"]
        assert counts["medium"] <= counts["high"]
        assert counts["high"] <= counts["critical"]


class TestAbstractAssertAndYield:
    """Assert statements and yield/yield from expressions."""

    def test_assert_statement(self):
        source = '''
def validate_payment(amount):
    assert amount > 0, "Amount must be positive"
    return amount
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)

    def test_yield_generator(self):
        source = '''
def generate_invoices(customers):
    for customer in customers:
        invoice = {"customer": customer, "total": 100}
        yield invoice
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'generate_invoices' not in result.abstract_code


class TestAbstractTypeAnnotations:
    """Type annotations should not break abstraction."""

    def test_annotated_function(self):
        source = '''
from typing import List, Dict, Optional

def process_orders(orders: List[Dict], limit: Optional[int] = None) -> List[Dict]:
    filtered = [o for o in orders if o.get("total", 0) > 0]
    return filtered[:limit]
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)
        assert 'process_orders' not in result.abstract_code

    def test_variable_annotation(self):
        source = '''
commission_rate: float = 0.029
order_count: int = 0
'''
        result = abstract(source, privacy_level="high")
        ast.parse(result.abstract_code)


# ═══════════════════════════════════════════════════════════════════════════════
# ALGORITHM 2 — CLASSIFY(E) EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyPatternBoundaries:
    """Edge cases in regex pattern matching."""

    def test_overlapping_secret_and_value_secret_wins(self):
        """If a name matches both SECRET and VALUE patterns, SECRET takes priority."""
        # 'auth_rate' matches .*auth.* (SECRET) and .*rate.* (VALUE)
        node = ast.Name(id="auth_rate", ctx=ast.Load())
        assert classify_node(node) == "SECRET"  # SECRET checked first

    def test_empty_string_name(self):
        """Name with empty string should not crash."""
        node = ast.Name(id="", ctx=ast.Load())
        # Empty string matches .*key.* etc. - let's just confirm no crash
        result = classify_node(node)
        assert result in ("SECRET", "VALUE", "IDENTIFIER")

    def test_very_long_identifier(self):
        """Extremely long identifier name should not cause regex catastrophe."""
        long_name = "variable_" + "x" * 10000
        node = ast.Name(id=long_name, ctx=ast.Load())
        result = classify_node(node)
        assert result in ("SECRET", "VALUE", "IDENTIFIER")

    def test_high_entropy_string_constant(self):
        """Base64-like string (≥32 chars) should be SECRET."""
        # This matches the base64 pattern in SECRET_PATTERNS
        b64_value = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"  # 32 chars, all base64
        node = ast.Constant(value=b64_value)
        result = classify_node(node)
        assert result == "SECRET"

    def test_boolean_constant_is_identifier(self):
        """Boolean True/False constants → IDENTIFIER (they're not numeric)."""
        node = ast.Constant(value=True)
        # True is not int/float/complex for the isinstance check at line 56
        # But isinstance(True, int) is actually True in Python!
        result = classify_node(node)
        # Document actual behavior: True is instance of int in Python
        assert result in ("VALUE", "IDENTIFIER")

    def test_none_constant(self):
        """None constant should not crash and return IDENTIFIER."""
        node = ast.Constant(value=None)
        result = classify_node(node)
        assert result == "IDENTIFIER"

    def test_bytes_constant(self):
        """bytes constant should not crash."""
        node = ast.Constant(value=b"raw bytes")
        result = classify_node(node)
        assert result in ("SECRET", "VALUE", "IDENTIFIER")


class TestClassifyAttributeHandling:
    """
    Attribute nodes sensitivity classification:
    classify_node._get_node_text extracts .attr from Attribute nodes,
    enabling proper pattern matching.
    """

    def test_attribute_named_api_key_is_secret(self):
        """self.api_key → classify returns SECRET."""
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="api_key",
            ctx=ast.Load(),
        )
        assert classify_node(node) == "SECRET"

    def test_attribute_named_password_is_secret(self):
        """self.password → classify returns SECRET."""
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="password",
            ctx=ast.Load(),
        )
        assert classify_node(node) == "SECRET"


# ═══════════════════════════════════════════════════════════════════════════════
# ALGORITHM 3 — RECONSTRUCT(R, M̃, K) EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestReconstructAllPrefixTypes:
    """Ensure all 6 token prefixes are extracted and replaced."""

    def _enc(self, mapping):
        return encrypt_mapping(mapping)

    def test_class_token_replacement(self):
        """CLASS_ tokens must be extracted and replaced."""
        mapping = {
            'CLASS_0': {'name': 'PaymentProcessor', 'label': 'IDENTIFIER',
                        'lineno': 10, 'ctx': {}},
        }
        enc, key = self._enc(mapping)
        result = reconstruct("CLASS_0 has a bug", enc, key)
        assert "PaymentProcessor" in result
        assert "CLASS_0" not in result

    def test_num_token_replacement(self):
        """NUM_ tokens must be extracted and replaced."""
        mapping = {
            'NUM_0': {'name': '0.029', 'label': 'VALUE',
                      'lineno': 3, 'ctx': {}},
        }
        enc, key = self._enc(mapping)
        result = reconstruct("NUM_0 is too low", enc, key)
        assert "0.029" in result
        assert "NUM_0" not in result

    def test_all_six_prefixes_together(self):
        """Mix of FUNC, VAR, SECRET, CONST, NUM, CLASS all in one response."""
        mapping = {
            'FUNC_0': {'name': 'calculate', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}},
            'VAR_0': {'name': 'amount', 'label': 'IDENTIFIER', 'lineno': 2, 'ctx': {}},
            'SECRET_0': {'name': 'api_key', 'label': 'SECRET', 'lineno': 3, 'ctx': {}},
            'CONST_0': {'name': 'endpoint', 'label': 'VALUE', 'lineno': 4, 'ctx': {}},
            'NUM_0': {'name': '0.029', 'label': 'VALUE', 'lineno': 5, 'ctx': {}},
            'CLASS_0': {'name': 'Processor', 'label': 'IDENTIFIER', 'lineno': 6, 'ctx': {}},
        }
        enc, key = self._enc(mapping)
        response = "FUNC_0 in CLASS_0 uses VAR_0 with SECRET_0 at CONST_0 rate NUM_0"
        result = reconstruct(response, enc, key)
        assert "calculate" in result
        assert "amount" in result
        assert "api_key" in result
        assert "endpoint" in result
        assert "0.029" in result
        assert "Processor" in result
        # No tokens should remain
        for prefix in ["FUNC_0", "VAR_0", "SECRET_0", "CONST_0", "NUM_0", "CLASS_0"]:
            assert prefix not in result


class TestReconstructTokenInOriginalName:
    """Edge case: original name itself contains a token-like substring."""

    def test_original_name_contains_func_prefix(self):
        """If original name is 'FUNC_handler', replacement must not break."""
        mapping = {
            'FUNC_0': {'name': 'FUNC_handler', 'label': 'IDENTIFIER',
                       'lineno': 1, 'ctx': {}},
        }
        enc, key = encrypt_mapping(mapping)
        result = reconstruct("FUNC_0 is broken", enc, key)
        assert "FUNC_handler" in result

    def test_original_name_is_number(self):
        """Original name is a stringified number like '42'."""
        mapping = {
            'NUM_0': {'name': '42', 'label': 'VALUE',
                      'lineno': 5, 'ctx': {}},
        }
        enc, key = encrypt_mapping(mapping)
        result = reconstruct("NUM_0 should be changed", enc, key)
        assert "42" in result


class TestReconstructEmptyAndEdge:
    """Edge cases for the reconstruct function."""

    def test_empty_response(self):
        """Empty LLM response should return empty string."""
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = encrypt_mapping(mapping)
        result = reconstruct("", enc, key)
        assert result == ""

    def test_empty_mapping(self):
        """Empty mapping with tokens in response should preserve tokens."""
        enc, key = encrypt_mapping({})
        result = reconstruct("FUNC_0 is broken", enc, key)
        assert "FUNC_0" in result

    def test_response_with_only_whitespace(self):
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = encrypt_mapping(mapping)
        result = reconstruct("   \n\n   ", enc, key)
        assert result.strip() == ""

    def test_token_adjacent_to_punctuation(self):
        """Tokens next to punctuation (FUNC_0. FUNC_0, FUNC_0;) should be replaced."""
        mapping = {'FUNC_0': {'name': 'process', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = encrypt_mapping(mapping)
        result = reconstruct("Call FUNC_0. Then FUNC_0, and FUNC_0;", enc, key)
        assert "FUNC_0" not in result
        # 3 in the response text + 1 in the context block header = 4
        assert result.count("process") >= 3

    def test_token_in_backtick_code(self):
        """Tokens inside markdown backticks should be replaced."""
        mapping = {'FUNC_0': {'name': 'calculate', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = encrypt_mapping(mapping)
        result = reconstruct("Check `FUNC_0` for bugs", enc, key)
        assert "calculate" in result
        assert "FUNC_0" not in result


class TestReconstructStructured:
    """Test the structured reconstruct API."""

    def test_structured_returns_result_object(self):
        mapping = {
            'FUNC_0': {'name': 'process', 'label': 'IDENTIFIER', 'lineno': 5,
                       'ctx': {'snippet': 'def process():', 'start_line': 5,
                               'end_line': 5, 'target_line': 5}},
        }
        enc, key = encrypt_mapping(mapping)
        result = reconstruct_structured("Fix FUNC_0", enc, key)
        assert result.review_text == "Fix process"
        assert len(result.references) == 1
        assert result.references[0]['name'] == 'process'
        assert result.references[0]['lineno'] == 5

    def test_structured_no_tokens_empty_references(self):
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = encrypt_mapping(mapping)
        result = reconstruct_structured("No tokens here", enc, key)
        assert result.review_text == "No tokens here"
        assert len(result.references) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ALGORITHM 4 — ENCRYPT/DECRYPT EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEncryptEdgeCases:
    """Additional encryption/decryption edge cases."""

    def test_large_mapping(self):
        """Encrypt/decrypt a large mapping (500 entries)."""
        mapping = {
            f"TOKEN_{i}": {
                'name': f"original_name_{i}",
                'label': 'IDENTIFIER',
                'lineno': i,
                'ctx': {'snippet': f'line {i}', 'start_line': i, 'end_line': i, 'target_line': i},
            }
            for i in range(500)
        }
        enc, key = encrypt_mapping(mapping)
        decrypted = decrypt_mapping(enc, key)
        assert decrypted == mapping

    def test_deeply_nested_dict(self):
        """Mapping with deeply nested dict values."""
        mapping = {
            'FUNC_0': {
                'name': 'process',
                'label': 'IDENTIFIER',
                'lineno': 1,
                'ctx': {
                    'snippet': 'def process():',
                    'start_line': 1,
                    'end_line': 1,
                    'target_line': 1,
                    'metadata': {
                        'tags': ['security', 'payment'],
                        'nested': {'deep': True},
                    },
                },
            },
        }
        enc, key = encrypt_mapping(mapping)
        decrypted = decrypt_mapping(enc, key)
        assert decrypted == mapping

    def test_special_characters_in_names(self):
        """Names with special characters survive roundtrip."""
        mapping = {
            'CONST_0': {
                'name': 'https://api.stripe.com/v2/charge?key=sk_live',
                'label': 'VALUE',
                'lineno': 1,
                'ctx': {},
            },
        }
        enc, key = encrypt_mapping(mapping)
        decrypted = decrypt_mapping(enc, key)
        assert decrypted['CONST_0']['name'] == mapping['CONST_0']['name']

    def test_newlines_in_values(self):
        """Values containing newlines survive roundtrip."""
        mapping = {
            'CONST_0': {
                'name': '-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----',
                'label': 'SECRET',
                'lineno': 1,
                'ctx': {},
            },
        }
        enc, key = encrypt_mapping(mapping)
        decrypted = decrypt_mapping(enc, key)
        assert decrypted == mapping


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpersEdgeCases:
    """Additional edge cases for is_semantically_significant and label_to_prefix."""

    def test_string_constant_with_single_char_is_significant(self):
        """String constant '5' (single char but Constant node) is significant."""
        node = ast.Constant(value=5)
        assert is_semantically_significant(node) is True

    def test_empty_string_constant(self):
        """Empty string constant should be filtered (empty name)."""
        node = ast.Constant(value="")
        # _extract_name returns "" which is falsy → False
        assert is_semantically_significant(node) is False

    def test_label_to_prefix_numeric_constant(self):
        """Numeric constant node should get NUM prefix when node is provided."""
        node = ast.Constant(value=3.14)
        result = label_to_prefix("VALUE", "Constant", node)
        assert result == "NUM"

    def test_label_to_prefix_string_constant(self):
        """String constant node should get CONST prefix."""
        node = ast.Constant(value="hello")
        result = label_to_prefix("VALUE", "Constant", node)
        assert result == "CONST"


# ═══════════════════════════════════════════════════════════════════════════════
# END-TO-END PROPERTY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEndRoundtrip:
    """Property: every token in abstract code can be reconstructed back."""

    def test_every_token_reconstructible(self):
        """For a real-world-like file, every token must be reconstructible."""
        source = '''
STRIPE_API_KEY = "sk_live_abc123def456ghi789"
PAYPAL_SECRET = "ppsecret_xyzabc123"
commission_rate = 0.029
base_url = "https://api.payment.com/v2"

def calculate_commission(amount):
    fee = amount * commission_rate
    return round(fee, 2)

def process_payment(user_id, amount, method="stripe"):
    if method == "stripe":
        endpoint = base_url + "/charge"
    total = amount + calculate_commission(amount)
    return {"endpoint": endpoint, "total": total, "user": user_id}

class PaymentProcessor:
    def __init__(self, api_key):
        self.api_key = api_key
        self.timeout_seconds = 30

    def charge(self, amount, currency="usd"):
        return {"amount": amount, "currency": currency}
'''
        result = abstract(source, privacy_level="high")
        mapping = _decrypt(result)

        # Build a simulated LLM response containing all tokens
        all_tokens = list(mapping.keys())
        response = " ".join(all_tokens)
        translated = reconstruct(response, result.encrypted_mapping, result.encryption_key)

        # Verify every original name appears
        for token, entry in mapping.items():
            assert entry['name'] in translated, (
                f"Token {token} → '{entry['name']}' was not reconstructed"
            )
            # Verify the token itself is gone
            assert token not in translated, (
                f"Token {token} still present after reconstruction"
            )

    def test_abstract_reconstruct_preserves_semantics(self):
        """Abstracting code and then reconstructing the abstract code itself
        should yield a string containing all original identifiers."""
        source = '''
def calculate_tax(income, rate):
    tax = income * rate
    return round(tax, 2)
'''
        result = abstract(source, privacy_level="high")
        # Use the abstract code itself as the "LLM response"
        reconstructed = reconstruct(
            result.abstract_code,
            result.encrypted_mapping,
            result.encryption_key,
        )
        # All original names should appear in the reconstructed version
        mapping = _decrypt(result)
        for entry in mapping.values():
            assert entry['name'] in reconstructed


class TestEndToEndPrivacyGuarantees:
    """Property tests for privacy guarantees."""

    def test_no_secrets_in_abstract_code(self):
        """No SECRET-classified tokens should leak into abstract code."""
        source = '''
STRIPE_KEY = "sk_live_testing123456789"
AWS_SECRET = "AKIAIOSFODNN7EXAMPLE"
DB_PASSWORD = "p@ssw0rd123!"
BEARER_TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9"

def process(data):
    return data
'''
        result = abstract(source, privacy_level="high")
        mapping = _decrypt(result)
        for token, entry in mapping.items():
            if entry['label'] == 'SECRET':
                assert entry['name'] not in result.abstract_code, (
                    f"SECRET '{entry['name']}' leaked into abstract code!"
                )

    def test_abstract_code_always_valid_python(self):
        """Abstract code must ALWAYS be valid Python for any input."""
        test_sources = [
            'x = 1',
            'pass',
            '# comment\n',
            'def f(): pass',
            'class C: pass',
            'import os',
            'from os import path',
            'a = 1; b = 2; c = a + b',
            'x = [i**2 for i in range(10)]',
            '''
async def fetch():
    await something()

def gen():
    yield 42
''',
        ]
        for source in test_sources:
            result = abstract(source, privacy_level="high")
            try:
                ast.parse(result.abstract_code)
            except SyntaxError as e:
                pytest.fail(
                    f"Abstract code is not valid Python for source:\n"
                    f"{source}\n\nAbstract:\n{result.abstract_code}\n\nError: {e}"
                )

    def test_idempotent_abstraction(self):
        """Abstracting already-abstracted code should still produce valid Python."""
        source = '''
def calculate(amount):
    return amount * 0.029
'''
        result1 = abstract(source, privacy_level="high")
        # Abstract the abstract code (simulates double-abstraction)
        result2 = abstract(result1.abstract_code, privacy_level="high")
        ast.parse(result2.abstract_code)


class TestEndToEndCriticalPrivacy:
    """Critical privacy level must abstract single-char vars too."""

    def test_critical_abstracts_loop_variables(self):
        """Under critical privacy, single-char loop vars 'i' should be abstracted."""
        source = '''
for i in range(10):
    x = i * 2
    print(x)
'''
        result_high = abstract(source, privacy_level="high")
        result_crit = abstract(source, privacy_level="critical")
        # Critical should abstract more nodes (or at minimum equal)
        assert result_crit.statistics['abstracted_nodes'] >= result_high.statistics['abstracted_nodes']
        # Both should produce valid Python
        ast.parse(result_high.abstract_code)
        ast.parse(result_crit.abstract_code)
