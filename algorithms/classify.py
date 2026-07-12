"""
CLASSIFY(E) Algorithm Implementation

Implements formal Algorithm 2 from specification.

Classifies AST nodes into sensitivity categories:
- SECRET: credentials, API keys, tokens, passwords
- VALUE: business-sensitive values (prices, rates, endpoints)
- IDENTIFIER: default classification
"""

import ast
import re
from typing import List, Literal

from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS
from core.pattern_matcher import matches_any

Label = Literal['SECRET', 'VALUE', 'IDENTIFIER']


def classify_node(node: ast.AST) -> Label:
    """
    CLASSIFY(E) — Sensitivity Classification Algorithm.

    Examines an AST node's name and literal value to determine
    its sensitivity classification.

    Args:
        node: AST node E.

    Returns:
        Label: 'SECRET', 'VALUE', or 'IDENTIFIER'.

    Implements:
        Algorithm 2 from formal specification.
    """
    # Step 1: Extract text signal from node
    text = _get_node_text(node)

    if not text:
        return 'IDENTIFIER'

    # Convert to lowercase for case-insensitive matching
    text_lower = text.lower()

    # Step 2: Check SECRET patterns
    if matches_any(text_lower, SECRET_PATTERNS):
        return 'SECRET'

    # Step 3: Check VALUE patterns
    if matches_any(text_lower, VALUE_PATTERNS):
        return 'VALUE'

    # Step 3b: Numeric constants are inherently business-sensitive
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex)):
        return 'VALUE'

    # Step 4: Default to IDENTIFIER
    return 'IDENTIFIER'


def _get_node_text(node: ast.AST) -> str:
    """
    Combine name(E) and literal_value(E) as text signal.

    Extracts all relevant textual information from the AST node
    to feed into pattern matching.

    Args:
        node: AST node.

    Returns:
        Combined text string for pattern matching.
    """
    text_parts: List[str] = []

    # Extract name from various node types
    if isinstance(node, ast.Name):
        text_parts.append(node.id)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        text_parts.append(node.name)
    elif isinstance(node, ast.ClassDef):
        text_parts.append(node.name)
    elif isinstance(node, ast.arg):
        text_parts.append(node.arg)

    # Extract literal value from Constant nodes
    if isinstance(node, ast.Constant):
        text_parts.append(str(node.value))

    # For assignment nodes, also check target names and values
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                text_parts.append(target.id)
        if isinstance(node.value, ast.Constant):
            text_parts.append(str(node.value.value))

    return ' '.join(text_parts)
