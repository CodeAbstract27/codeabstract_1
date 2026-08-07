"""
Privacy Leakage Metric — Pillar 1

Measures how much sensitive information survives abstraction.

Metric: Privacy Information Ratio (PIR)
    PIR = 1 - (sensitive_tokens_abstracted / total_sensitive_tokens_found)

A PIR of 0.0 = perfect privacy (everything abstracted).
A PIR of 1.0 = no privacy (nothing abstracted).

Sub-metrics:
    secret_leakage_rate   — fraction of SECRET nodes still verbatim in output
    value_leakage_rate    — fraction of VALUE nodes still verbatim in output
    identifier_leakage_rate — fraction of IDENTIFIER nodes still verbatim (high level)
    overall_pir           — weighted average across all categories
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from algorithms.abstract import abstract
from algorithms.classify import classify_node
from algorithms.encrypt import decrypt_mapping
from evaluation.benchmarks.corpus import ALL_FILES


@dataclass
class PrivacyResult:
    """Privacy metrics for a single file."""

    file_name: str
    privacy_level: str
    total_sensitive_nodes: int
    total_abstracted: int
    secret_total: int
    secret_abstracted: int
    value_total: int
    value_abstracted: int
    identifier_total: int
    identifier_abstracted: int
    secret_leakage_rate: float
    value_leakage_rate: float
    identifier_leakage_rate: float
    overall_pir: float
    abstract_code_snippet: str = ""


@dataclass
class PrivacySuiteResult:
    """Aggregated privacy metrics across all corpus files."""

    per_file: List[PrivacyResult] = field(default_factory=list)
    mean_pir: float = 0.0
    mean_secret_leakage: float = 0.0
    mean_value_leakage: float = 0.0
    mean_identifier_leakage: float = 0.0
    syntax_validity_rate: float = 0.0
    files_evaluated: int = 0


def _count_original_labels(source_code: str) -> Dict[str, List[str]]:
    """
    Parse source and collect all node names by their classification label.

    Returns dict: {'SECRET': [...names], 'VALUE': [...names], 'IDENTIFIER': [...names]}
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return {"SECRET": [], "VALUE": [], "IDENTIFIER": []}

    from algorithms.helpers import is_semantically_significant
    from algorithms.helpers import BUILTINS

    labels: Dict[str, List[str]] = {"SECRET": [], "VALUE": [], "IDENTIFIER": []}

    for node in ast.walk(tree):
        if not is_semantically_significant(node):
            continue
        name = _get_name(node)
        if not name:
            continue
        label = classify_node(node)
        labels[label].append(name)

    return labels


def _get_name(node: ast.AST) -> Optional[str]:
    """Extract the text name from a node."""
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


def evaluate_file_privacy(
    source_code: str,
    file_name: str,
    privacy_level: str = "high",
) -> PrivacyResult:
    """
    Compute privacy metrics for a single source file.

    Args:
        source_code: Python source code.
        file_name: Label for reporting.
        privacy_level: Abstraction level (low/medium/high/critical).

    Returns:
        PrivacyResult with per-category leakage rates and overall PIR.
    """
    # Collect original labels
    original_labels = _count_original_labels(source_code)

    # Run abstraction
    result = abstract(source_code, privacy_level=privacy_level)
    abstract_code = result.abstract_code

    # Check syntax validity of abstract output
    try:
        ast.parse(abstract_code)
        syntax_valid = True
    except SyntaxError:
        syntax_valid = False

    # Decrypt mapping to find what was abstracted
    mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
    abstracted_names = {entry["name"] for entry in mapping.values()}

    # Per-category counts
    def count_leaked(names: List[str]) -> int:
        """Count names that still appear verbatim in abstract code."""
        leaked = 0
        for name in names:
            # Use word-boundary matching for accuracy
            if name and re.search(r'\b' + re.escape(name) + r'\b', abstract_code):
                leaked += 1
        return leaked

    secret_names = original_labels["SECRET"]
    value_names = original_labels["VALUE"]
    ident_names = original_labels["IDENTIFIER"]

    secret_leaked = count_leaked(secret_names)
    value_leaked = count_leaked(value_names)
    ident_leaked = count_leaked(ident_names)

    secret_abstracted = len(secret_names) - secret_leaked
    value_abstracted = len(value_names) - value_leaked
    ident_abstracted = len(ident_names) - ident_leaked

    # Leakage rates (0.0 = none leaked, 1.0 = all leaked)
    def leakage_rate(leaked: int, total: int) -> float:
        return round(leaked / total, 4) if total > 0 else 0.0

    secret_lr = leakage_rate(secret_leaked, len(secret_names))
    value_lr = leakage_rate(value_leaked, len(value_names))
    ident_lr = leakage_rate(ident_leaked, len(ident_names))

    # Overall PIR — weighted by counts
    total_sensitive = len(secret_names) + len(value_names)
    total_sensitive_abstracted = secret_abstracted + value_abstracted

    if total_sensitive > 0:
        pir = 1.0 - (total_sensitive_abstracted / total_sensitive)
    else:
        pir = 0.0

    return PrivacyResult(
        file_name=file_name,
        privacy_level=privacy_level,
        total_sensitive_nodes=total_sensitive,
        total_abstracted=total_sensitive_abstracted,
        secret_total=len(secret_names),
        secret_abstracted=secret_abstracted,
        value_total=len(value_names),
        value_abstracted=value_abstracted,
        identifier_total=len(ident_names),
        identifier_abstracted=ident_abstracted,
        secret_leakage_rate=secret_lr,
        value_leakage_rate=value_lr,
        identifier_leakage_rate=ident_lr,
        overall_pir=round(pir, 4),
        abstract_code_snippet=abstract_code[:200],
    )


def run_privacy_suite(privacy_level: str = "high") -> PrivacySuiteResult:
    """
    Run privacy evaluation across all corpus files.

    Args:
        privacy_level: Abstraction level to test.

    Returns:
        PrivacySuiteResult with per-file results and aggregated means.
    """
    suite = PrivacySuiteResult()
    syntax_valid_count = 0

    for file_entry in ALL_FILES:
        result = evaluate_file_privacy(
            source_code=file_entry["code"],
            file_name=file_entry["name"],
            privacy_level=privacy_level,
        )
        suite.per_file.append(result)

        # Track syntax validity
        try:
            ast.parse(abstract(file_entry["code"], privacy_level=privacy_level).abstract_code)
            syntax_valid_count += 1
        except SyntaxError:
            pass

    n = len(suite.per_file)
    suite.files_evaluated = n

    if n > 0:
        suite.mean_pir = round(sum(r.overall_pir for r in suite.per_file) / n, 4)
        suite.mean_secret_leakage = round(
            sum(r.secret_leakage_rate for r in suite.per_file) / n, 4
        )
        suite.mean_value_leakage = round(
            sum(r.value_leakage_rate for r in suite.per_file) / n, 4
        )
        suite.mean_identifier_leakage = round(
            sum(r.identifier_leakage_rate for r in suite.per_file) / n, 4
        )
        suite.syntax_validity_rate = round(syntax_valid_count / n, 4)

    return suite
