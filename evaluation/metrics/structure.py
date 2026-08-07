"""
Code Structure Preservation Metric — Pillar 4

Proves that abstraction does NOT corrupt the structural integrity of code.

Metrics:
    ast_isomorphism_score  — Fraction of AST node types preserved exactly
                             (1.0 = perfect structural preservation)
    cyclomatic_complexity_delta — Difference in cyclomatic complexity
                             (should be 0: abstraction doesn't change logic)
    token_count_ratio      — abstract_tokens / original_tokens
                             (measures abstraction density)
    syntax_validity_rate   — % of files where abstract output is valid Python
                             (should be 100%)
    abstraction_density    — tokens_abstracted / total_identifiers_in_original
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from algorithms.abstract import abstract
from evaluation.benchmarks.corpus import ALL_FILES


@dataclass
class StructureResult:
    """Code structure preservation metrics for a single file."""

    file_name: str
    syntax_valid: bool
    ast_isomorphism_score: float
    cyclomatic_complexity_original: int
    cyclomatic_complexity_abstract: int
    cyclomatic_complexity_delta: int
    token_count_original: int
    token_count_abstract: int
    token_count_ratio: float
    abstraction_density: float
    total_nodes_original: int
    total_nodes_abstract: int


@dataclass
class StructureSuiteResult:
    """Aggregated structure metrics across all corpus files."""

    per_file: List[StructureResult] = field(default_factory=list)
    syntax_validity_rate: float = 0.0
    mean_ast_isomorphism: float = 0.0
    mean_complexity_delta: float = 0.0
    mean_token_ratio: float = 0.0
    mean_abstraction_density: float = 0.0
    files_evaluated: int = 0


def _compute_cyclomatic_complexity(source_code: str) -> int:
    """
    Compute a simple approximation of cyclomatic complexity.

    Counts: function defs + if/elif + for + while + except + and/or
    Each represents an independent execution path (McCabe's metric).
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return 0

    complexity = 1  # Base complexity
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(node, (ast.BoolOp,)):
            # Each extra operand in and/or adds a path
            complexity += len(node.values) - 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Each function is its own scope baseline
            pass
    return complexity


def _get_ast_node_type_sequence(source_code: str) -> List[str]:
    """
    Extract a flat sequence of AST node type names from source code.

    Used to compare structural shape between original and abstract.
    """
    try:
        tree = ast.parse(source_code)
        return [type(n).__name__ for n in ast.walk(tree)]
    except SyntaxError:
        return []


def _ast_isomorphism_score(original_seq: List[str], abstract_seq: List[str]) -> float:
    """
    Compare two AST node type sequences.

    Computes the fraction of node types that appear in the same proportions.
    Abstract may have slightly different Name/Constant ratios but should
    preserve If/For/While/FunctionDef/ClassDef structure exactly.

    Returns 0.0–1.0, where 1.0 means identical node type distributions.
    """
    if not original_seq:
        return 1.0

    # Count node type frequencies
    def freq(seq: List[str]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in seq:
            counts[s] = counts.get(s, 0) + 1
        return counts

    orig_freq = freq(original_seq)
    abst_freq = freq(abstract_seq)

    # Focus on structural node types (control flow, definitions)
    structural_types = {
        "FunctionDef", "AsyncFunctionDef", "ClassDef",
        "If", "For", "While", "Try", "ExceptHandler",
        "Return", "Assign", "AugAssign", "AnnAssign",
        "Call", "BoolOp", "Compare", "BinOp",
        "With", "Assert", "Raise", "Import", "ImportFrom",
    }

    match_score = 0
    total_structural = 0

    for node_type in structural_types:
        orig_count = orig_freq.get(node_type, 0)
        abst_count = abst_freq.get(node_type, 0)
        if orig_count > 0:
            total_structural += orig_count
            # Count how many match (min of both)
            match_score += min(orig_count, abst_count)

    if total_structural == 0:
        return 1.0

    return round(match_score / total_structural, 4)


def _count_python_tokens(source_code: str) -> int:
    """Count the number of Python tokens in source code."""
    import tokenize
    import io
    tokens = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source_code).readline):
            if tok.type not in (
                tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER,
            ):
                tokens += 1
    except tokenize.TokenError:
        # Fallback: split on whitespace
        tokens = len(source_code.split())
    return tokens


def _count_identifiers(source_code: str) -> int:
    """Count all identifier/name nodes in the AST."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.arg, ast.FunctionDef,
                              ast.AsyncFunctionDef, ast.ClassDef,
                              ast.Attribute)):
            count += 1
    return count


def evaluate_file_structure(
    source_code: str,
    file_name: str,
    privacy_level: str = "high",
) -> StructureResult:
    """
    Compute structure preservation metrics for a single source file.

    Args:
        source_code: Python source code.
        file_name: Label for reporting.
        privacy_level: Abstraction level.

    Returns:
        StructureResult with all structural metrics.
    """
    # Run abstraction
    result = abstract(source_code, privacy_level=privacy_level)
    abstract_code = result.abstract_code

    # Syntax validity
    try:
        ast.parse(abstract_code)
        syntax_valid = True
    except SyntaxError:
        syntax_valid = False

    # AST node type sequences
    original_seq = _get_ast_node_type_sequence(source_code)
    abstract_seq = _get_ast_node_type_sequence(abstract_code)

    # Isomorphism score
    isomorphism = _ast_isomorphism_score(original_seq, abstract_seq)

    # Cyclomatic complexity
    cc_original = _compute_cyclomatic_complexity(source_code)
    cc_abstract = _compute_cyclomatic_complexity(abstract_code)
    cc_delta = abs(cc_original - cc_abstract)

    # Token counts
    tokens_original = _count_python_tokens(source_code)
    tokens_abstract = _count_python_tokens(abstract_code)
    token_ratio = round(tokens_abstract / tokens_original, 4) if tokens_original > 0 else 1.0

    # Abstraction density
    total_identifiers = _count_identifiers(source_code)
    abstracted_count = result.statistics.get("abstracted_nodes", 0)
    density = round(abstracted_count / total_identifiers, 4) if total_identifiers > 0 else 0.0

    return StructureResult(
        file_name=file_name,
        syntax_valid=syntax_valid,
        ast_isomorphism_score=isomorphism,
        cyclomatic_complexity_original=cc_original,
        cyclomatic_complexity_abstract=cc_abstract,
        cyclomatic_complexity_delta=cc_delta,
        token_count_original=tokens_original,
        token_count_abstract=tokens_abstract,
        token_count_ratio=token_ratio,
        abstraction_density=density,
        total_nodes_original=len(original_seq),
        total_nodes_abstract=len(abstract_seq),
    )


def run_structure_suite(privacy_level: str = "high") -> StructureSuiteResult:
    """
    Run structure preservation evaluation across all corpus files.

    Returns:
        StructureSuiteResult with per-file and aggregated metrics.
    """
    suite = StructureSuiteResult()

    for file_entry in ALL_FILES:
        result = evaluate_file_structure(
            source_code=file_entry["code"],
            file_name=file_entry["name"],
            privacy_level=privacy_level,
        )
        suite.per_file.append(result)

    n = len(suite.per_file)
    suite.files_evaluated = n

    if n > 0:
        suite.syntax_validity_rate = round(
            sum(1 for r in suite.per_file if r.syntax_valid) / n, 4
        )
        suite.mean_ast_isomorphism = round(
            sum(r.ast_isomorphism_score for r in suite.per_file) / n, 4
        )
        suite.mean_complexity_delta = round(
            sum(r.cyclomatic_complexity_delta for r in suite.per_file) / n, 4
        )
        suite.mean_token_ratio = round(
            sum(r.token_count_ratio for r in suite.per_file) / n, 4
        )
        suite.mean_abstraction_density = round(
            sum(r.abstraction_density for r in suite.per_file) / n, 4
        )

    return suite
