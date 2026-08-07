"""
Classification Accuracy Metric — Pillar 3

Measures how accurately CLASSIFY(E) assigns sensitivity labels.

Uses a hand-labeled ground-truth dataset of 150 AST nodes.

Metrics:
    precision   — per class (SECRET / VALUE / IDENTIFIER)
    recall      — per class
    f1_score    — per class
    macro_f1    — unweighted mean F1 across all 3 classes
    confusion_matrix — 3×3 matrix (rows=true, cols=predicted)
    overall_accuracy — fraction of nodes correctly classified
"""

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from algorithms.classify import classify_node
from evaluation.benchmarks.labeled_nodes import ALL_LABELED_NODES, LabeledNode


CLASSES = ["SECRET", "VALUE", "IDENTIFIER"]


@dataclass
class ClassMetrics:
    """Precision, recall, F1 for one class."""
    label: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    support: int = 0    # number of ground-truth instances


@dataclass
class ClassificationResult:
    """Full classification evaluation result."""
    per_class: Dict[str, ClassMetrics] = field(default_factory=dict)
    macro_f1: float = 0.0
    macro_precision: float = 0.0
    macro_recall: float = 0.0
    overall_accuracy: float = 0.0
    confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_nodes: int = 0
    correctly_classified: int = 0
    # Per-domain breakdown
    domain_accuracy: Dict[str, float] = field(default_factory=dict)


def _make_synthetic_node(node_name: str, node_type: str) -> ast.AST:
    """
    Construct a minimal synthetic AST node for classification.

    Since CLASSIFY uses node names and literal values, we reconstruct
    the appropriate node type from the labeled dataset entry.
    """
    if node_type == "Name":
        node = ast.Name(id=node_name, ctx=ast.Load())
    elif node_type == "FunctionDef":
        node = ast.FunctionDef(
            name=node_name,
            args=ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]
            ),
            body=[ast.Pass()],
            decorator_list=[],
        )
    elif node_type == "ClassDef":
        node = ast.ClassDef(
            name=node_name,
            bases=[], keywords=[],
            body=[ast.Pass()],
            decorator_list=[],
        )
    elif node_type == "arg":
        node = ast.arg(arg=node_name)
    elif node_type == "Constant":
        # Try to infer numeric vs string
        try:
            value = float(node_name)
            if node_name.isdigit():
                value = int(node_name)
        except (ValueError, AttributeError):
            value = node_name
        node = ast.Constant(value=value)
    elif node_type == "Attribute":
        node = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr=node_name,
            ctx=ast.Load(),
        )
    else:
        # Fallback: Name node
        node = ast.Name(id=node_name, ctx=ast.Load())

    ast.fix_missing_locations(node)
    return node


def run_classification_evaluation() -> ClassificationResult:
    """
    Run CLASSIFY on all 150 labeled nodes and compute metrics.

    Returns:
        ClassificationResult with per-class metrics, macro F1,
        confusion matrix, and accuracy.
    """
    result = ClassificationResult()
    result.total_nodes = len(ALL_LABELED_NODES)

    # Initialize confusion matrix: rows = true label, cols = predicted
    conf_matrix: Dict[str, Dict[str, int]] = {
        cls: {c: 0 for c in CLASSES} for cls in CLASSES
    }

    # Initialize per-class counters
    tp: Dict[str, int] = {c: 0 for c in CLASSES}
    fp: Dict[str, int] = {c: 0 for c in CLASSES}
    fn: Dict[str, int] = {c: 0 for c in CLASSES}
    support: Dict[str, int] = {c: 0 for c in CLASSES}

    # Per-domain tracking
    domain_totals: Dict[str, int] = {}
    domain_correct: Dict[str, int] = {}

    correctly_classified = 0

    for labeled_node in ALL_LABELED_NODES:
        true_label = labeled_node.expected_label
        domain = labeled_node.domain

        # Build synthetic AST node
        node = _make_synthetic_node(labeled_node.node_name, labeled_node.node_type)

        # Run CLASSIFY
        predicted_label = classify_node(node)

        # Update confusion matrix
        conf_matrix[true_label][predicted_label] += 1

        # Update TP/FP/FN
        support[true_label] += 1
        if predicted_label == true_label:
            tp[true_label] += 1
            correctly_classified += 1
        else:
            fp[predicted_label] += 1
            fn[true_label] += 1

        # Domain tracking
        domain_totals[domain] = domain_totals.get(domain, 0) + 1
        if predicted_label == true_label:
            domain_correct[domain] = domain_correct.get(domain, 0) + 1

    # Compute per-class precision, recall, F1
    per_class: Dict[str, ClassMetrics] = {}
    for cls in CLASSES:
        cm = ClassMetrics(label=cls)
        cm.true_positives = tp[cls]
        cm.false_positives = fp[cls]
        cm.false_negatives = fn[cls]
        cm.support = support[cls]

        denom_p = tp[cls] + fp[cls]
        denom_r = tp[cls] + fn[cls]

        cm.precision = round(tp[cls] / denom_p, 4) if denom_p > 0 else 0.0
        cm.recall = round(tp[cls] / denom_r, 4) if denom_r > 0 else 0.0

        denom_f1 = cm.precision + cm.recall
        cm.f1 = (
            round(2 * cm.precision * cm.recall / denom_f1, 4)
            if denom_f1 > 0 else 0.0
        )
        per_class[cls] = cm

    result.per_class = per_class
    result.confusion_matrix = conf_matrix
    result.correctly_classified = correctly_classified

    # Macro metrics (unweighted mean across classes)
    result.macro_f1 = round(sum(c.f1 for c in per_class.values()) / len(CLASSES), 4)
    result.macro_precision = round(
        sum(c.precision for c in per_class.values()) / len(CLASSES), 4
    )
    result.macro_recall = round(
        sum(c.recall for c in per_class.values()) / len(CLASSES), 4
    )
    result.overall_accuracy = round(correctly_classified / result.total_nodes, 4)

    # Domain accuracy
    result.domain_accuracy = {
        domain: round(domain_correct.get(domain, 0) / total, 4)
        for domain, total in domain_totals.items()
    }

    return result
