"""
ABSTRACT(S, k) Algorithm Implementation

Implements formal Algorithm 1 from specification.

Performs AST-based semantic abstraction to transform proprietary
Python code into privacy-safe intermediate representation.
"""
"""Formal Algorithm -1"""
import ast
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from algorithms.classify import classify_node
from algorithms.encrypt import encrypt_mapping
from algorithms.helpers import (
    is_semantically_significant,
    label_to_prefix,
)
from core.context_extractor import get_context
from core.token_generator import TokenGenerator


@dataclass
class AbstractionResult:
    """Result of the ABSTRACT(S, k) algorithm."""

    abstract_code: str
    encrypted_mapping: bytes
    encryption_key: bytes
    session_id: str
    statistics: Dict = field(default_factory=dict)


def abstract(
    source_code: str,
    context_window: int = 3,
    privacy_level: str = "high",
) -> AbstractionResult:
    """
    ABSTRACT(S, k) — Semantic Abstraction Algorithm.

    Parses Python source code into an AST, traverses all nodes,
    classifies each identifier/constant for sensitivity, generates
    unique tokens with consistent reuse, replaces nodes in the AST,
    then unparses back to abstract source code.  The mapping table
    is encrypted with Fernet before returning.

    Args:
        source_code: Python source code S.
        context_window: Context window size k (default: 3).
        privacy_level: Privacy level (low|medium|high|critical).

    Returns:
        AbstractionResult containing abstract code, encrypted mapping,
        encryption key, session ID, and statistics.

    Raises:
        ValueError: If the source code contains syntax errors.

    Implements:
        Algorithm 1 from formal specification.
    """
    # ───────────────────────────────────────────────────
    # Step 1: Parse source code to AST
    # ───────────────────────────────────────────────────
    try:
        ast_tree = ast.parse(source_code)
    except SyntaxError as e:
        raise ValueError(f"Invalid Python syntax at line {e.lineno}: {e.msg}")

    # ───────────────────────────────────────────────────
    # Step 2: Initialize data structures
    # ───────────────────────────────────────────────────
    mapping_table: Dict[str, Dict] = {}  # M in the algorithm
    counters = {'FUNC': 0, 'VAR': 0, 'SECRET': 0, 'CONST': 0, 'CLASS': 0, 'NUM': 0}
    seen: Dict[str, str] = {}            # name → token cache for consistency

    # Step 3: Token generator
    token_gen = TokenGenerator(counters)

    # Step 4: Statistics tracking
    stats = {
        'total_nodes': 0,
        'abstracted_nodes': 0,
        'skipped_nodes': 0,
        'secrets_found': 0,
        'values_found': 0,
    }

    # ───────────────────────────────────────────────────
    # Step 5a: Build parent map (needed to swap Constant → Name nodes)
    # ───────────────────────────────────────────────────
    parent_map: Dict[int, ast.AST] = {}
    for node in ast.walk(ast_tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node

    # ───────────────────────────────────────────────────
    # Step 5b: Collect Constant nodes inside f-strings (JoinedStr)
    #          Only Constants are skipped (literal text fragments);
    #          Name nodes inside f-strings are still abstracted.
    # ───────────────────────────────────────────────────
    fstring_children: set = set()
    for node in ast.walk(ast_tree):
        if isinstance(node, ast.JoinedStr):
            for child in ast.walk(node):
                if isinstance(child, ast.Constant):
                    fstring_children.add(id(child))

    # ───────────────────────────────────────────────────
    # Step 5c: Traverse AST
    # ───────────────────────────────────────────────────
    for node in ast.walk(ast_tree):
        stats['total_nodes'] += 1

        # Skip nodes inside f-strings (prevents f-string corruption)
        if id(node) in fstring_children:
            stats['skipped_nodes'] += 1
            continue

        # Step 6: Skip non-significant nodes
        if not is_semantically_significant(node):
            stats['skipped_nodes'] += 1
            continue

        # Extract node name
        node_name = _get_node_name(node)
        if not node_name:
            stats['skipped_nodes'] += 1
            continue

        # Step 7: Classify node
        label = classify_node(node)

        # Check privacy level filtering
        if not _should_abstract(label, privacy_level):
            stats['skipped_nodes'] += 1
            continue

        # Update statistics
        if label == 'SECRET':
            stats['secrets_found'] += 1
        elif label == 'VALUE':
            stats['values_found'] += 1

        # Step 8: Token generation (with reuse)
        if node_name in seen:
            # Reuse existing token for consistency
            token = seen[node_name]
        else:
            # Determine effective node type for prefix selection.
            # If this Attribute is the func of a Call, treat as method → FUNC.
            node_type_name = type(node).__name__
            if isinstance(node, ast.Attribute):
                parent = parent_map.get(id(node))
                if isinstance(parent, ast.Call) and parent.func is node:
                    node_type_name = 'FunctionDef'  # → FUNC prefix

            # Generate new token
            prefix = label_to_prefix(label, node_type_name, node)
            token = token_gen.generate(prefix)

            # Extract context (need lineno)
            lineno = getattr(node, 'lineno', 1)
            ctx = get_context(source_code, lineno, context_window)

            # Store in mapping table
            mapping_table[token] = {
                'name': node_name,
                'label': label,
                'node_type': type(node).__name__,
                'lineno': lineno,
                'ctx': ctx,
            }

            # Cache token for reuse
            seen[node_name] = token

        # Step 9: Replace node in AST
        _replace_node_name(node, token, parent_map)
        stats['abstracted_nodes'] += 1

    # ───────────────────────────────────────────────────
    # Step 10: Unparse AST to abstract code
    # ───────────────────────────────────────────────────
    abstract_code = ast.unparse(ast_tree)

    # ───────────────────────────────────────────────────
    # Step 11: Encrypt mapping
    # ───────────────────────────────────────────────────
    encrypted_mapping, encryption_key = encrypt_mapping(mapping_table)

    # ───────────────────────────────────────────────────
    # Step 12: Generate session ID
    # ───────────────────────────────────────────────────
    session_id = str(uuid.uuid4())

    return AbstractionResult(
        abstract_code=abstract_code,
        encrypted_mapping=encrypted_mapping,
        encryption_key=encryption_key,
        session_id=session_id,
        statistics=stats,
    )


# ═══════════════════════════════════════════════════════════
# Private helper functions
# ═══════════════════════════════════════════════════════════

def _get_node_name(node: ast.AST) -> Optional[str]:
    """Extract the identifier name from an AST node."""
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


def _replace_node_name(
    node: ast.AST,
    token: str,
    parent_map: Optional[Dict[int, ast.AST]] = None,
):
    """
    Replace the node's identifier with the given token.

    For Constant nodes, swaps the node with an ast.Name so that
    ast.unparse() emits the token *unquoted* (e.g. ``CONST_1``
    instead of ``'CONST_1'``).
    """
    if isinstance(node, ast.Name):
        node.id = token
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.name = token
    elif isinstance(node, ast.ClassDef):
        node.name = token
    elif isinstance(node, ast.arg):
        node.arg = token
    elif isinstance(node, ast.Attribute):
        node.attr = token
    elif isinstance(node, ast.Constant):
        # Swap Constant → Name so unparse doesn't add quotes
        replacement = ast.Name(id=token, ctx=ast.Load())
        ast.copy_location(node, replacement)
        if parent_map is not None:
            parent = parent_map.get(id(node))
            if parent:
                _swap_child(parent, node, replacement)
                return
        # Fallback: modify value in-place (will be quoted)
        node.value = token


def _swap_child(
    parent: ast.AST,
    old_node: ast.AST,
    new_node: ast.AST,
):
    """
    Replace *old_node* with *new_node* inside *parent*.

    Walks every field of the parent AST node.  If the field holds
    a single node reference, it is replaced directly via setattr.
    If the field holds a list (e.g. ``body``, ``targets``), the
    matching element is swapped in-place.
    """
    for field, value in ast.iter_fields(parent):
        if value is old_node:
            setattr(parent, field, new_node)
            return
        if isinstance(value, list):
            for i, item in enumerate(value):
                if item is old_node:
                    value[i] = new_node
                    return


def _should_abstract(label: str, privacy_level: str) -> bool:
    """
    Determine whether a node should be abstracted based on its
    classification label and the current privacy level.

    Privacy levels control aggressiveness:
    - low:      Only SECRET
    - medium:   SECRET + VALUE
    - high:     SECRET + VALUE + IDENTIFIER
    - critical: Everything
    """
    if privacy_level == "low":
        return label == 'SECRET'
    elif privacy_level == "medium":
        return label in ('SECRET','VALUE')
    elif privacy_level in ("high", "critical"):
        return True  # Abstract everything
    else:
        # Default to medium behaviour
        return label in ('SECRET', 'VALUE')
