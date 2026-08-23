"""
Tests for algorithms/helpers.py

Covers:
- is_semantically_significant(): all filter rules
- label_to_prefix(): all label/node-type combinations
"""

import ast
import pytest

from algorithms.helpers import is_semantically_significant, label_to_prefix


# ═══════════════════════════════════════════════════════════
# Tests for is_semantically_significant()
# ═══════════════════════════════════════════════════════════

class TestIsSemanticallySig:
    """Test suite for IsSemanticallySig(E) helper."""

    # ─── Rule 1: Skip builtins ─────────────────────────────

    @pytest.mark.parametrize("builtin_name", [
        "print", "len", "range", "str", "int", "float", "bool",
        "list", "dict", "set", "tuple", "isinstance", "type",
        "sum", "max", "min", "abs", "round", "sorted", "zip",
        "enumerate", "map", "filter", "any", "all", "open",
        "super", "property", "staticmethod", "classmethod",
    ])
    def test_skips_builtin_functions(self, builtin_name):
        """Built-in function names should NOT be abstracted."""
        node = ast.Name(id=builtin_name, ctx=ast.Load())
        assert is_semantically_significant(node) is False

    @pytest.mark.parametrize("builtin_const", [
        "self", "cls", "None", "True", "False",
        "NotImplemented", "Ellipsis",
    ])
    def test_skips_builtin_constants(self, builtin_const):
        """Built-in constant names should NOT be abstracted."""
        node = ast.Name(id=builtin_const, ctx=ast.Load())
        assert is_semantically_significant(node) is False

    @pytest.mark.parametrize("exc_name", [
        "Exception", "ValueError", "TypeError", "KeyError",
        "RuntimeError", "FileNotFoundError", "StopIteration",
    ])
    def test_skips_builtin_exceptions(self, exc_name):
        """Standard exception class names should NOT be abstracted."""
        node = ast.Name(id=exc_name, ctx=ast.Load())
        assert is_semantically_significant(node) is False

    # ─── Rule 2: Skip single-char names ───────────────────

    @pytest.mark.parametrize("single_char", ["i", "j", "k", "x", "y", "z", "n", "a", "b"])
    def test_skips_single_char_names(self, single_char):
        """Single-character variable names should NOT be abstracted."""
        node = ast.Name(id=single_char, ctx=ast.Load())
        assert is_semantically_significant(node) is False

    def test_single_char_skips_name_not_constant(self):
        """Single-char rule applies to Name nodes; Constant nodes with short values still pass."""
        # A Name node with id='x' → skip
        name_node = ast.Name(id="x", ctx=ast.Load())
        assert is_semantically_significant(name_node) is False

    # ─── Rule 3: Skip dunder names ─────────────────────────

    @pytest.mark.parametrize("dunder", [
        "__init__", "__main__", "__name__", "__str__",
        "__repr__", "__len__", "__all__", "__slots__",
    ])
    def test_skips_dunder_names(self, dunder):
        """Dunder method/attribute names should NOT be abstracted."""
        node = ast.FunctionDef(
            name=dunder,
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[ast.Pass()], decorator_list=[], returns=None,
        )
        assert is_semantically_significant(node) is False

    # ─── Significant nodes (should return True) ─────────────

    @pytest.mark.parametrize("name", [
        "calculate_commission", "process_payment", "user_data",
        "payment_gateway", "order_service", "api_handler",
    ])
    def test_significant_identifiers(self, name):
        """Multi-char non-builtin names SHOULD be abstracted."""
        node = ast.Name(id=name, ctx=ast.Load())
        assert is_semantically_significant(node) is True

    def test_significant_function_def(self):
        """Non-dunder FunctionDef nodes SHOULD be abstracted."""
        node = ast.FunctionDef(
            name="calculate_total",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[ast.Pass()], decorator_list=[], returns=None,
        )
        assert is_semantically_significant(node) is True

    def test_significant_class_def(self):
        """ClassDef nodes SHOULD be abstracted."""
        node = ast.ClassDef(
            name="PaymentProcessor",
            bases=[], keywords=[], body=[ast.Pass()], decorator_list=[],
        )
        assert is_semantically_significant(node) is True

    def test_significant_arg_node(self):
        """Function argument nodes with meaningful names SHOULD be abstracted."""
        node = ast.arg(arg="payment_amount", annotation=None)
        assert is_semantically_significant(node) is True

    def test_significant_attribute_node(self):
        """Attribute nodes with meaningful names SHOULD be abstracted."""
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr="payment_gateway",
            ctx=ast.Load(),
        )
        assert is_semantically_significant(node) is True

    def test_numeric_constant_is_significant(self):
        """Numeric constants (int/float) are semantically significant."""
        node = ast.Constant(value=0.029)
        assert is_semantically_significant(node) is True

    def test_integer_constant_is_significant(self):
        """Integer constants are semantically significant."""
        node = ast.Constant(value=30)
        assert is_semantically_significant(node) is True

    def test_unsupported_node_type_returns_false(self):
        """AST node types with no name extraction return False."""
        node = ast.Pass()
        assert is_semantically_significant(node) is False

    def test_if_node_returns_false(self):
        """If nodes have no identifier name and should not be abstracted."""
        node = ast.If(test=ast.Constant(value=True), body=[], orelse=[])
        assert is_semantically_significant(node) is False

    def test_async_function_def_is_significant(self):
        """AsyncFunctionDef is significant (non-dunder)."""
        node = ast.AsyncFunctionDef(
            name="fetch_data",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[ast.Pass()], decorator_list=[], returns=None,
        )
        assert is_semantically_significant(node) is True

    def test_two_char_name_is_significant(self):
        """Two-character names (e.g. 'id') should pass the single-char filter."""
        node = ast.Name(id="id", ctx=ast.Load())
        # 'id' is a builtin, so it should be skipped
        assert is_semantically_significant(node) is False

    def test_two_char_non_builtin_is_significant(self):
        """Two-character non-builtin name like 'tx' should be abstracted."""
        node = ast.Name(id="tx", ctx=ast.Load())
        assert is_semantically_significant(node) is True


# ═══════════════════════════════════════════════════════════
# Tests for label_to_prefix()
# ═══════════════════════════════════════════════════════════

class TestLabelToPrefix:
    """Test suite for LabelToPrefix(label, type) helper."""

    # ─── Rule 1: SECRET always → 'SECRET' ─────────────────

    @pytest.mark.parametrize("node_type", [
        "Name", "FunctionDef", "AsyncFunctionDef", "ClassDef",
        "Constant", "arg", "Attribute",
    ])
    def test_secret_label_always_returns_secret(self, node_type):
        """SECRET label must always return 'SECRET' regardless of node type."""
        assert label_to_prefix("SECRET", node_type) == "SECRET"

    # ─── Rule 2: FunctionDef → 'FUNC' ─────────────────────

    def test_function_def_returns_func(self):
        assert label_to_prefix("IDENTIFIER", "FunctionDef") == "FUNC"

    def test_async_function_def_returns_func(self):
        assert label_to_prefix("IDENTIFIER", "AsyncFunctionDef") == "FUNC"

    def test_value_function_def_returns_func(self):
        """Even VALUE-labelled functions get FUNC prefix (function type wins)."""
        assert label_to_prefix("VALUE", "FunctionDef") == "FUNC"

    # ─── Rule 3: ClassDef → 'CLASS' ───────────────────────

    def test_class_def_returns_class(self):
        assert label_to_prefix("IDENTIFIER", "ClassDef") == "CLASS"

    def test_value_class_def_returns_class(self):
        assert label_to_prefix("VALUE", "ClassDef") == "CLASS"

    # ─── Rule 4: Constant → 'CONST' ───────────────────────

    def test_constant_returns_const(self):
        assert label_to_prefix("IDENTIFIER", "Constant") == "CONST"

    def test_value_constant_returns_const(self):
        assert label_to_prefix("VALUE", "Constant") == "CONST"

    # ─── Rule 5: Default → 'VAR' ──────────────────────────

    def test_name_node_returns_var(self):
        assert label_to_prefix("IDENTIFIER", "Name") == "VAR"

    def test_arg_node_returns_var(self):
        assert label_to_prefix("IDENTIFIER", "arg") == "VAR"

    def test_attribute_node_returns_var(self):
        assert label_to_prefix("IDENTIFIER", "Attribute") == "VAR"

    def test_value_name_returns_var(self):
        """VALUE-labelled Name nodes get VAR prefix."""
        assert label_to_prefix("VALUE", "Name") == "VAR"

    def test_unknown_node_type_returns_var(self):
        """Completely unknown node type should fall through to VAR."""
        assert label_to_prefix("IDENTIFIER", "UnknownNodeXYZ") == "VAR"
