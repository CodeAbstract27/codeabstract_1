"""Tests for CLASSIFY(E) algorithm."""

import ast
import pytest

from algorithms.classify import classify_node


class TestClassify:
    """Test suite for Algorithm 2: CLASSIFY(E)."""

    # ─── SECRET patterns ──────────────────────────────

    @pytest.mark.parametrize("name,expected", [
        ("STRIPE_API_KEY", "SECRET"),
        ("api_key", "SECRET"),
        ("user_token", "SECRET"),
        ("access_token", "SECRET"),
        ("password", "SECRET"),
        ("db_password", "SECRET"),
        ("secret_value", "SECRET"),
        ("auth_header", "SECRET"),
        ("credential_store", "SECRET"),
        ("private_key", "SECRET"),
        ("bearer_token", "SECRET"),
    ])
    def test_classify_secret_names(self, name, expected):
        """Identifiers matching SECRET patterns should return SECRET."""
        node = ast.Name(id=name, ctx=ast.Load())
        assert classify_node(node) == expected

    # ─── VALUE patterns ───────────────────────────────

    @pytest.mark.parametrize("name,expected", [
        ("commission_rate", "VALUE"),
        ("base_price", "VALUE"),
        ("service_fee", "VALUE"),
        ("api_endpoint", "VALUE"),
        ("timeout_seconds", "VALUE"),
        ("rate_limit", "VALUE"),
        ("total_amount", "VALUE"),
        ("max_threshold", "VALUE"),
        ("config_path", "VALUE"),
        ("discount_rate", "VALUE"),
    ])
    def test_classify_value_names(self, name, expected):
        """Identifiers matching VALUE patterns should return VALUE."""
        node = ast.Name(id=name, ctx=ast.Load())
        assert classify_node(node) == expected

    # ─── IDENTIFIER (default) ─────────────────────────

    @pytest.mark.parametrize("name", [
        "calculate", "process", "handler", "manager",
        "user_name", "data", "items", "counter",
    ])
    def test_classify_identifier_default(self, name):
        """Non-matching identifiers should return IDENTIFIER."""
        node = ast.Name(id=name, ctx=ast.Load())
        assert classify_node(node) == "IDENTIFIER"

    # ─── Function definitions ─────────────────────────

    def test_classify_function_with_secret_name(self):
        """FunctionDef with secret-matching name → SECRET."""
        node = ast.FunctionDef(
            name="get_auth_token",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[], decorator_list=[], returns=None,
        )
        assert classify_node(node) == "SECRET"

    def test_classify_function_with_value_name(self):
        """FunctionDef with value-matching name → VALUE."""
        node = ast.FunctionDef(
            name="calculate_total_price",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[], decorator_list=[], returns=None,
        )
        assert classify_node(node) == "VALUE"

    def test_classify_function_identifier(self):
        """FunctionDef with generic name → IDENTIFIER."""
        node = ast.FunctionDef(
            name="process_data",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[], decorator_list=[], returns=None,
        )
        assert classify_node(node) == "IDENTIFIER"

    # ─── arg nodes ────────────────────────────────────

    def test_classify_arg_secret(self):
        """Function argument with secret name."""
        node = ast.arg(arg="api_key", annotation=None)
        assert classify_node(node) == "SECRET"

    def test_classify_arg_value(self):
        """Function argument with value name."""
        node = ast.arg(arg="timeout", annotation=None)
        assert classify_node(node) == "VALUE"

    # ─── Case insensitivity ───────────────────────────

    def test_classify_case_insensitive(self):
        """Classification should be case-insensitive."""
        node = ast.Name(id="API_KEY", ctx=ast.Load())
        assert classify_node(node) == "SECRET"

        node2 = ast.Name(id="Api_Key", ctx=ast.Load())
        assert classify_node(node2) == "SECRET"


# ═══════════════════════════════════════════════════════════
# Additional gap-filling tests
# ═══════════════════════════════════════════════════════════

class TestClassifyConstantNodes:
    """Constant AST nodes (string and numeric) classification."""

    def test_numeric_int_constant_is_value(self):
        """Integer constants should classify as VALUE (business-sensitive numbers)."""
        node = ast.Constant(value=30)
        assert classify_node(node) == "VALUE"

    def test_numeric_float_constant_is_value(self):
        """Float constants should classify as VALUE."""
        node = ast.Constant(value=0.029)
        assert classify_node(node) == "VALUE"

    def test_string_constant_matching_secret_pattern(self):
        """String constant whose value contains 'key' or 'token' → SECRET."""
        # 'my_api_key_value' contains 'key' → matches '.*key.*'
        node = ast.Constant(value="my_api_key_value")
        assert classify_node(node) == "SECRET"

    def test_string_constant_with_password_word(self):
        """String 'supersecret' matches '.*secret.*' → SECRET."""
        node = ast.Constant(value="supersecret")
        assert classify_node(node) == "SECRET"

    def test_string_constant_generic_is_identifier(self):
        """A plain string constant ('hello') → IDENTIFIER (no special pattern)."""
        node = ast.Constant(value="hello")
        assert classify_node(node) == "IDENTIFIER"

    def test_complex_constant_is_value(self):
        """Complex number constants → VALUE."""
        node = ast.Constant(value=3+4j)
        assert classify_node(node) == "VALUE"

    @pytest.mark.parametrize("val", [0, 1, -1, 100, 3.14, 0.0])
    def test_various_numerics_are_value(self, val):
        """All numeric literal constants should be VALUE."""
        node = ast.Constant(value=val)
        assert classify_node(node) == "VALUE"


class TestClassifyAttributeNodes:
    """Attribute AST nodes classification.

    Note: The classify module's _get_node_text does NOT extract `.attr`
    from Attribute nodes (it is not a handled type there). Attribute nodes
    therefore always return IDENTIFIER from classify_node directly.
    The actual Attribute abstraction relies on is_semantically_significant
    and label_to_prefix, not on classify_node's pattern matching.
    These tests document and lock in the current behaviour.
    """

    def test_attribute_node_returns_identifier(self):
        """Attribute nodes currently return IDENTIFIER (no pattern matching on .attr)."""
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="api_key",
            ctx=ast.Load(),
        )
        # Current behaviour: Attribute has no text in _get_node_text → IDENTIFIER
        assert classify_node(node) == "IDENTIFIER"

    def test_attribute_timeout_returns_identifier(self):
        """Even value-named attributes return IDENTIFIER from classify_node."""
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="timeout_seconds",
            ctx=ast.Load(),
        )
        assert classify_node(node) == "IDENTIFIER"

    def test_attribute_generic_is_identifier(self):
        """Generic attribute name should classify as IDENTIFIER."""
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="handler",
            ctx=ast.Load(),
        )
        assert classify_node(node) == "IDENTIFIER"


class TestClassifyAsyncFunctionDef:
    """AsyncFunctionDef nodes follow the same classification as FunctionDef."""

    def test_async_func_secret_name(self):
        """Async function with secret name → SECRET."""
        node = ast.AsyncFunctionDef(
            name="get_api_token",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[], decorator_list=[], returns=None,
        )
        assert classify_node(node) == "SECRET"

    def test_async_func_identifier(self):
        """Async function with generic name → IDENTIFIER."""
        node = ast.AsyncFunctionDef(
            name="fetch_data",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[], decorator_list=[], returns=None,
        )
        assert classify_node(node) == "IDENTIFIER"


class TestClassifyClassDef:
    """ClassDef nodes classification."""

    def test_class_with_generic_name_is_identifier(self):
        """Generic class name → IDENTIFIER."""
        node = ast.ClassDef(
            name="PaymentProcessor",
            bases=[], keywords=[], body=[ast.Pass()], decorator_list=[],
        )
        assert classify_node(node) == "IDENTIFIER"

    def test_class_with_secret_name(self):
        """Class named 'AuthCredential' should match secret pattern."""
        node = ast.ClassDef(
            name="AuthCredential",
            bases=[], keywords=[], body=[ast.Pass()], decorator_list=[],
        )
        assert classify_node(node) == "SECRET"


class TestClassifyUnsupportedNodes:
    """Nodes with no text signal default to IDENTIFIER."""

    def test_pass_node_is_identifier(self):
        """Pass node has no name → falls through to IDENTIFIER."""
        node = ast.Pass()
        assert classify_node(node) == "IDENTIFIER"

    def test_if_node_is_identifier(self):
        """If node has no name signal → IDENTIFIER."""
        node = ast.If(test=ast.Constant(value=True), body=[], orelse=[])
        assert classify_node(node) == "IDENTIFIER"
