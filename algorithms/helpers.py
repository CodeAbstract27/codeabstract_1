"""
Helper Algorithm Implementations

Implements helper functions from formal specification:
- IsSemanticallySig(E): Determines if an AST node should be abstracted
- LabelToPrefix(label, type): Maps classification label to token prefix
"""

import ast
from typing import Optional, Set

# ═══════════════════════════════════════════════════════════
# Python builtins that should NOT be abstracted
# ═══════════════════════════════════════════════════════════

BUILTINS: Set[str] = {
    # Built-in functions
    'print', 'len', 'range', 'str', 'int', 'float', 'bool',
    'list', 'dict', 'set', 'tuple', 'type', 'isinstance',
    'hasattr', 'getattr', 'setattr', 'delattr', 'input', 'open',
    'sum', 'max', 'min', 'abs', 'round', 'sorted', 'reversed',
    'enumerate', 'zip', 'map', 'filter', 'any', 'all',
    'iter', 'next', 'id', 'hash', 'repr', 'format',
    'chr', 'ord', 'hex', 'oct', 'bin',
    'object', 'bytes', 'bytearray', 'memoryview',
    'complex', 'frozenset',
    'callable', 'dir', 'vars', 'globals', 'locals',
    'exec', 'eval', 'compile',
    'issubclass', 'super',
    'property', 'staticmethod', 'classmethod',
    'breakpoint', 'exit', 'quit',

    # Constants / keywords used as identifiers
    'self', 'cls', 'None', 'True', 'False',
    'NotImplemented', 'Ellipsis',

    # Common exception types
    'Exception', 'ValueError', 'TypeError', 'KeyError',
    'IndexError', 'AttributeError', 'RuntimeError',
    'FileNotFoundError', 'IOError', 'OSError',
    'StopIteration', 'GeneratorExit',
    'ImportError', 'ModuleNotFoundError',
    'NameError', 'UnboundLocalError',
    'ZeroDivisionError', 'OverflowError',
    'AssertionError', 'NotImplementedError',
}


def is_semantically_significant(node: ast.AST) -> bool:
    """
    IsSemanticallySig(E) — Node Filter.

    Determines whether an AST node carries semantic meaning that
    should be abstracted.  Filters out builtins, single-character
    loop variables, and dunder names.

    Args:
        node: AST node E.

    Returns:
        True if the node should be abstracted, False otherwise.

    Implements:
        IsSemanticallySig helper from formal specification.
    """
    name = _extract_name(node)

    if not name:
        return False

    # Rule 1: Skip builtins
    if name in BUILTINS:
        return False

    # Rule 2: Skip single-character names (loop vars: i, j, x, y, …)
    if len(name) <= 1:
        return False

    # Rule 3: Skip dunder names (__init__, __main__, __name__, …)
    if name.startswith('__') and name.endswith('__'):
        return False

    # All checks passed — semantically significant
    return True


def _extract_name(node: ast.AST) -> Optional[str]:
    """Extract the identifier name from an AST node, or None."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    elif isinstance(node, ast.ClassDef):
        return node.name
    elif isinstance(node, ast.arg):
        return node.arg
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None


def label_to_prefix(label: str, node_type: str) -> str:
    """
    LabelToPrefix(label, type) — Token Prefix Selector.

    Maps a classification label and AST node type to the appropriate
    token prefix.

    Args:
        label: Classification label ('SECRET', 'VALUE', or 'IDENTIFIER').
        node_type: Name of the AST node type (e.g. 'FunctionDef', 'Name').

    Returns:
        Token prefix string: 'SECRET', 'FUNC', 'CONST', or 'VAR'.

    Implements:
        LabelToPrefix helper from formal specification.
    """
    # Rule 1: SECRET label always → "SECRET"
    if label == 'SECRET':
        return 'SECRET'

    # Rule 2: Function definitions → "FUNC"
    if node_type in ('FunctionDef', 'AsyncFunctionDef'):
        return 'FUNC'

    # Rule 3: Constants → "CONST"
    if node_type == 'Constant':
        return 'CONST'

    # Rule 4: Default → "VAR"
    return 'VAR'
