"""
Detector Comparison Harness

Phase 2.

The classification pillar reports a single macro-F1 for a single detector.
That is enough to say "the classifier scores 0.89" and not enough to say
"the hybrid detector is better than the regex baseline", which is the claim
Phase 2 exists to support.

This module compares *named detectors* on a *given dataset* and reports the
difference with a paired bootstrap confidence interval. The interval is the
point: with a small or weakly discriminative dataset, a plausible-looking
gap in point estimates comes with an interval spanning zero, and the honest
conclusion is that the data cannot tell the detectors apart.

Two dataset shapes are supported, because the detectors under test do not
all consume the same input:

* **node-level** — ``(name, type, label)`` triples, as in the legacy
  dataset. Name-based detectors work here. *Context detectors cannot*:
  usage signals need surrounding code, and a bare identifier has none.
  The harness reports this rather than silently scoring context features
  at zero.
* **code-level** — a source snippet plus the label for a named node.
  Everything works here.
"""

import ast
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

LABELS = ('SECRET', 'VALUE', 'IDENTIFIER')


@dataclass
class Sample:
    """One evaluation item, in either supported shape."""

    name: str
    node_type: str
    label: str
    code: str = ""          # optional surrounding source

    @property
    def has_context(self) -> bool:
        """True if this sample carries the code a context detector needs."""
        return bool(self.code.strip())


@dataclass
class ClassScore:
    """Precision / recall / F1 for one class."""

    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class DetectorScore:
    """A detector's performance on a dataset."""

    name: str
    accuracy: float
    macro_f1: float
    per_class: Dict[str, ClassScore] = field(default_factory=dict)
    predictions: List[str] = field(default_factory=list)
    context_available: bool = True

    # Recall on SECRET is the safety-critical number: a missed secret is a
    # leak, while a false positive only costs utility.
    @property
    def secret_recall(self) -> float:
        entry = self.per_class.get('SECRET')
        return entry.recall if entry else 0.0

    @property
    def secret_precision(self) -> float:
        entry = self.per_class.get('SECRET')
        return entry.precision if entry else 0.0


@dataclass
class Comparison:
    """A paired comparison between two detectors."""

    baseline: str
    candidate: str
    metric: str
    baseline_value: float
    candidate_value: float
    difference: float
    ci_low: float
    ci_high: float
    n_bootstrap: int

    @property
    def significant(self) -> bool:
        """True if the interval excludes zero."""
        return (self.ci_low > 0.0) or (self.ci_high < 0.0)

    def describe(self) -> str:
        verdict = (
            "significant" if self.significant
            else "not distinguishable — the interval spans zero"
        )
        return (
            f"{self.metric}: {self.candidate} {self.candidate_value:.4f} vs "
            f"{self.baseline} {self.baseline_value:.4f} "
            f"(Δ {self.difference:+.4f}, 95% CI "
            f"[{self.ci_low:+.4f}, {self.ci_high:+.4f}]) — {verdict}"
        )


# ═══════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════

def score_predictions(
    name: str,
    y_true: Sequence[str],
    y_pred: Sequence[str],
    context_available: bool = True,
) -> DetectorScore:
    """
    Compute accuracy, per-class precision/recall/F1, and macro-F1.

    Args:
        name: Detector name for reporting.
        y_true: Ground-truth labels.
        y_pred: Predicted labels, item-aligned.
        context_available: Whether the detector could see surrounding code.

    Returns:
        A :class:`DetectorScore`.

    Raises:
        ValueError: If the sequences differ in length or are empty.
    """
    if len(y_true) != len(y_pred):
        raise ValueError("prediction and truth sequences differ in length")
    if not y_true:
        raise ValueError("no items to score")

    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    per_class: Dict[str, ClassScore] = {}

    for label in LABELS:
        true_positive = sum(
            1 for t, p in zip(y_true, y_pred) if t == label and p == label
        )
        false_positive = sum(
            1 for t, p in zip(y_true, y_pred) if t != label and p == label
        )
        false_negative = sum(
            1 for t, p in zip(y_true, y_pred) if t == label and p != label
        )
        support = sum(1 for t in y_true if t == label)

        precision = (
            true_positive / (true_positive + false_positive)
            if (true_positive + false_positive) else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if (true_positive + false_negative) else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) else 0.0
        )

        per_class[label] = ClassScore(
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
            support=support,
        )

    macro_f1 = sum(c.f1 for c in per_class.values()) / len(per_class)

    return DetectorScore(
        name=name,
        accuracy=round(correct / len(y_true), 4),
        macro_f1=round(macro_f1, 4),
        per_class=per_class,
        predictions=list(y_pred),
        context_available=context_available,
    )


def _metric_value(y_true: Sequence[str], y_pred: Sequence[str], metric: str) -> float:
    """Compute one named metric over a (possibly resampled) set of items."""
    score = score_predictions("_", y_true, y_pred)
    if metric == 'macro_f1':
        return score.macro_f1
    if metric == 'accuracy':
        return score.accuracy
    if metric == 'secret_recall':
        return score.secret_recall
    if metric == 'secret_precision':
        return score.secret_precision
    raise ValueError(f"unknown metric: {metric}")


def paired_bootstrap(
    y_true: Sequence[str],
    pred_baseline: Sequence[str],
    pred_candidate: Sequence[str],
    metric: str = 'macro_f1',
    n_bootstrap: int = 2000,
    seed: int = 20260818,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
) -> Comparison:
    """
    Bootstrap a confidence interval on the *difference* between detectors.

    Resampling is paired — the same resampled items are scored under both
    detectors — because the two predictions are made on identical inputs
    and an unpaired interval would be needlessly wide.

    Args:
        y_true: Ground-truth labels.
        pred_baseline: Baseline detector's predictions.
        pred_candidate: Candidate detector's predictions.
        metric: One of ``macro_f1``, ``accuracy``, ``secret_recall``,
            ``secret_precision``.
        n_bootstrap: Resampling iterations.
        seed: Fixed for reproducibility — every number in the report must
            be regenerable.
        baseline_name: Label for reporting.
        candidate_name: Label for reporting.

    Returns:
        A :class:`Comparison` with a 95% percentile interval.
    """
    rng = random.Random(seed)
    n = len(y_true)

    observed_baseline = _metric_value(y_true, pred_baseline, metric)
    observed_candidate = _metric_value(y_true, pred_candidate, metric)

    differences: List[float] = []
    indices = range(n)

    for _ in range(n_bootstrap):
        sample = [rng.choice(indices) for _ in indices]
        truth = [y_true[i] for i in sample]
        base = [pred_baseline[i] for i in sample]
        cand = [pred_candidate[i] for i in sample]
        try:
            differences.append(
                _metric_value(truth, cand, metric) - _metric_value(truth, base, metric)
            )
        except ValueError:
            continue

    differences.sort()
    if differences:
        low = differences[int(0.025 * len(differences))]
        high = differences[min(int(0.975 * len(differences)), len(differences) - 1)]
    else:
        low = high = 0.0

    return Comparison(
        baseline=baseline_name,
        candidate=candidate_name,
        metric=metric,
        baseline_value=round(observed_baseline, 4),
        candidate_value=round(observed_candidate, 4),
        difference=round(observed_candidate - observed_baseline, 4),
        ci_low=round(low, 4),
        ci_high=round(high, 4),
        n_bootstrap=n_bootstrap,
    )


# ═══════════════════════════════════════════════════════════
# Detectors
# ═══════════════════════════════════════════════════════════

def detector_regex(sample: Sample) -> str:
    """The original name-pattern classifier, used as the baseline."""
    from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS
    from core.pattern_matcher import matches_any

    text = sample.name.lower()
    if matches_any(text, SECRET_PATTERNS):
        return 'SECRET'
    if matches_any(text, VALUE_PATTERNS):
        return 'VALUE'
    if sample.node_type == 'Constant':
        try:
            float(sample.name)
            return 'VALUE'
        except ValueError:
            pass
    return 'IDENTIFIER'


def _build_node(sample: Sample) -> ast.AST:
    """Reconstruct a minimal AST node from a node-level sample."""
    if sample.node_type == 'Constant':
        try:
            value = float(sample.name)
            value = int(value) if value.is_integer() else value
        except ValueError:
            value = sample.name
        return ast.Constant(value=value)
    if sample.node_type in ('FunctionDef', 'AsyncFunctionDef'):
        return ast.FunctionDef(
            name=sample.name,
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]),
            body=[], decorator_list=[], returns=None,
        )
    if sample.node_type == 'ClassDef':
        return ast.ClassDef(
            name=sample.name, bases=[], keywords=[],
            body=[], decorator_list=[],
        )
    if sample.node_type == 'arg':
        return ast.arg(arg=sample.name, annotation=None)
    if sample.node_type == 'Attribute':
        return ast.Attribute(
            value=ast.Name(id='self', ctx=ast.Load()),
            attr=sample.name, ctx=ast.Load(),
        )
    return ast.Name(id=sample.name, ctx=ast.Load())


def detector_hybrid(sample: Sample) -> str:
    """
    The Phase 2 hybrid detector: shape, then context, then name, then entropy.

    On a node-level sample the context tier has nothing to work with, so
    this degrades to shape + name + entropy. That is a property of the
    dataset, not of the detector, and the harness reports it.
    """
    from algorithms.classify import classify_with_evidence

    if sample.has_context:
        from core.context_features import analyze_context
        try:
            tree = ast.parse(sample.code)
        except SyntaxError:
            tree = None

        if tree is not None:
            evidence = analyze_context(tree)
            for node in ast.walk(tree):
                found = None
                if isinstance(node, ast.Name):
                    found = node.id
                elif isinstance(node, ast.Constant):
                    found = str(node.value)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef)):
                    found = node.name
                elif isinstance(node, ast.arg):
                    found = node.arg
                elif isinstance(node, ast.Attribute):
                    found = node.attr

                if found == sample.name:
                    return classify_with_evidence(
                        node, None, evidence.get(id(node))
                    ).label

    return classify_with_evidence(_build_node(sample), None, None).label


DETECTORS: Dict[str, Callable[[Sample], str]] = {
    'regex-baseline': detector_regex,
    'hybrid': detector_hybrid,
}


def evaluate_detector(
    name: str,
    dataset: Sequence[Sample],
    detector: Optional[Callable[[Sample], str]] = None,
) -> DetectorScore:
    """
    Run one detector across a dataset and score it.

    Args:
        name: Detector name; looked up in :data:`DETECTORS` if no callable
            is supplied.
        dataset: The evaluation samples.
        detector: Optional explicit callable.

    Returns:
        A :class:`DetectorScore`.
    """
    function = detector or DETECTORS[name]
    y_true = [sample.label for sample in dataset]
    y_pred = [function(sample) for sample in dataset]
    context_available = any(sample.has_context for sample in dataset)
    return score_predictions(name, y_true, y_pred, context_available)


def compare_on_dataset(
    dataset: Sequence[Sample],
    baseline: str = 'regex-baseline',
    candidate: str = 'hybrid',
    metrics: Tuple[str, ...] = ('macro_f1', 'secret_recall', 'secret_precision'),
    n_bootstrap: int = 2000,
) -> Dict[str, object]:
    """
    Score two detectors on a dataset and bootstrap the differences.

    Args:
        dataset: Evaluation samples.
        baseline: Baseline detector name.
        candidate: Candidate detector name.
        metrics: Metrics to compare.
        n_bootstrap: Resampling iterations.

    Returns:
        ``{'scores': {name: DetectorScore}, 'comparisons': [Comparison],
        'context_available': bool}``.
    """
    baseline_score = evaluate_detector(baseline, dataset)
    candidate_score = evaluate_detector(candidate, dataset)
    y_true = [sample.label for sample in dataset]

    comparisons = [
        paired_bootstrap(
            y_true,
            baseline_score.predictions,
            candidate_score.predictions,
            metric=metric,
            n_bootstrap=n_bootstrap,
            baseline_name=baseline,
            candidate_name=candidate,
        )
        for metric in metrics
    ]

    return {
        'scores': {baseline: baseline_score, candidate: candidate_score},
        'comparisons': comparisons,
        'context_available': candidate_score.context_available,
    }


def samples_from_legacy() -> List[Sample]:
    """Load the legacy node-level dataset as evaluation samples."""
    from evaluation.benchmarks.labeled_nodes import ALL_LABELED_NODES

    return [
        Sample(
            name=item.node_name,
            node_type=item.node_type,
            label=item.expected_label,
        )
        for item in ALL_LABELED_NODES
    ]
