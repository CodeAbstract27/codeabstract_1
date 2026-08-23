"""
Unit tests for core/ast_parser.py

Tests AST parsing, unparsing, node name extraction, and node name mutation.
"""

import ast
import pytest
from core.ast_parser import parse_source, unparse_ast, get_node_name, set_node_name


def test_parse_valid_source():
    """TC-AST-01: Valid Python code string should parse into ast.Module."""
    code = "def calculate_total(price, tax):\n    return price + tax"
    tree = parse_source(code)
    assert isinstance(tree, ast.Module)
    assert len(tree.body) == 1
    assert isinstance(tree.body[0], ast.FunctionDef)


def test_parse_invalid_syntax_raises_value_error():
    """TC-AST-02: Invalid syntax should raise ValueError with line info."""
    code = "def broken_func(:"
    with pytest.raises(ValueError, match="Invalid Python syntax at line 1"):
        parse_source(code)


def test_unparse_ast():
    """TC-AST-03: AST tree should unparse back to valid Python source code."""
    code = "x = 10 + 20"
    tree = parse_source(code)
    result_code = unparse_ast(tree)
    assert "x = 10 + 20" in result_code


def test_get_node_name():
    """TC-AST-04: Node names should be correctly extracted for supported AST types."""
    code = """
class PaymentProcessor:
    def process(self, amount):
        self.api_key = "sk_live_123"
        return amount
"""
    tree = parse_source(code)
    class_node = tree.body[0]
    func_node = class_node.body[0]
    arg_node = func_node.args.args[1]
    assign_node = func_node.body[0]
    attr_node = assign_node.targets[0]
    const_node = assign_node.value

    assert get_node_name(class_node) == "PaymentProcessor"
    assert get_node_name(func_node) == "process"
    assert get_node_name(arg_node) == "amount"
    assert get_node_name(attr_node) == "api_key"
    assert get_node_name(const_node) == "sk_live_123"


def test_get_node_name_unsupported():
    """Unsupported AST nodes should return None."""
    node = ast.Pass()
    assert get_node_name(node) is None


def test_set_node_name():
    """TC-AST-05: Node identifiers and values should be successfully mutated."""
    code = "def handle_payment(user_id):\n    self.key = 'secret_val'"
    tree = parse_source(code)
    func_node = tree.body[0]
    arg_node = func_node.args.args[0]
    assign_node = func_node.body[0]
    attr_node = assign_node.targets[0]
    const_node = assign_node.value

    assert set_node_name(func_node, "FUNC_0") is True
    assert set_node_name(arg_node, "VAR_0") is True
    assert set_node_name(attr_node, "SECRET_0") is True
    assert set_node_name(const_node, "CONST_0") is True

    assert func_node.name == "FUNC_0"
    assert arg_node.arg == "VAR_0"
    assert attr_node.attr == "SECRET_0"
    assert const_node.value == "CONST_0"


def test_set_node_name_unsupported():
    """Unsupported AST nodes should return False."""
    node = ast.Pass()
    assert set_node_name(node, "TOKEN") is False
