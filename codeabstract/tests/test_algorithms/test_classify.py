"""Tests for CLASSIFY(E) algorithm."""

import ast
import pytest

from codeabstract.algorithms.classify import classify_node


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
