"""
AST Parsing Utilities

Provides wrappers around Python's ast module for parsing,
unparsing, and inspecting Abstract Syntax Trees.
"""

import ast
from typing import Optional


def parse_source(source_code: str) -> ast.Module:
    """
    Parse Python source code into an AST.

    Args:
        source_code: Python source code string.

    Returns:
        Parsed ast.Module tree.

    Raises:
        ValueError: If the source code contains syntax errors.
    """
    try:
        tree = ast.parse(source_code)
        return tree
    except SyntaxError as e:
        raise ValueError(
            f"Invalid Python syntax at line {e.lineno}: {e.msg}"
        ) from e


def unparse_ast(tree: ast.AST) -> str:
    """
    Convert an AST back to Python source code.

    Args:
        tree: AST tree to unparse.

    Returns:
        Python source code string.
    """
    return ast.unparse(tree)


def get_node_name(node: ast.AST) -> Optional[str]:
    """
    Extract the identifier name from an AST node.

    Handles: Name, FunctionDef, AsyncFunctionDef, ClassDef, arg, Constant.

    Args:
        node: AST node.

    Returns:
        The identifier string, or None if the node type is not supported.
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    elif isinstance(node, ast.ClassDef):
        return node.name
    elif isinstance(node, ast.arg):
        return node.arg
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None


def set_node_name(node: ast.AST, token: str) -> bool:
    """
    Replace the identifier name of an AST node with a token.

    Args:
        node: AST node to modify.
        token: Replacement token string.

    Returns:
        True if replacement was performed, False if node type
        does not support name replacement.
    """
    if isinstance(node, ast.Name):
        node.id = token
        return True
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.name = token
        return True
    elif isinstance(node, ast.ClassDef):
        node.name = token
        return True
    elif isinstance(node, ast.arg):
        node.arg = token
        return True
    elif isinstance(node, ast.Attribute):
        node.attr = token
        return True
    elif isinstance(node, ast.Constant):
        node.value = token
        return True
    return False


