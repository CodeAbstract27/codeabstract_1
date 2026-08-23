"""
Random Forest Sensitivity Classifier

Phase 2 — the interpretable ML baseline the proposal specifies.

Trains a Random Forest over the shape features in :mod:`ml.features` and
reports cross-validated accuracy, per-class scores, feature importances,
and — the number that matters most here — **how often it agrees with the
regex baseline it was trained against**.

That last metric exists because of what the dataset audit found. When the
labels were derived from the shipped patterns, a model trained on them
cannot learn anything except those patterns: high agreement with the
baseline is the *expected* result, and reporting accuracy without it would
present regurgitation as performance.

:func:`train_and_report` therefore refuses to present its scores as an
evaluation unless the dataset passes a circularity check. It still trains
and still reports, but the result is labelled for what it is.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ml.features import FEATURE_NAMES, build_matrix

DEFAULT_SEED = 20260818


@dataclass
class TrainingReport:
    """Outcome of training the Random Forest on a dataset."""

    n_samples: int
    n_features: int
    cv_folds: int
    cv_accuracy_mean: float
    cv_accuracy_std: float
    per_class_f1: Dict[str, float] = field(default_factory=dict)
    feature_importances: List[tuple] = field(default_factory=list)
    agreement_with_regex: float = 0.0
    dataset_discriminative_power: float = 0.0
    trustworthy: bool = False
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Multi-line human-readable summary."""
        lines = [
            f"Random Forest — {self.n_samples} samples, "
            f"{self.n_features} features, {self.cv_folds}-fold CV",
            f"  CV accuracy          : {self.cv_accuracy_mean:.4f} "
            f"± {self.cv_accuracy_std:.4f}",
            f"  agreement with regex : {self.agreement_with_regex:.4f}",
            f"  dataset discriminative power: "
            f"{self.dataset_discriminative_power:.4f}",
            f"  trustworthy as an evaluation: {self.trustworthy}",
        ]
        if self.feature_importances:
            lines.append("  top features:")
            for name, importance in self.feature_importances[:6]:
                lines.append(f"    {name:24s} {importance:.4f}")
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def is_available() -> bool:
    """True if scikit-learn is installed."""
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


def train_and_report(
    samples: Sequence,
    cv_folds: int = 5,
    seed: int = DEFAULT_SEED,
    n_estimators: int = 200,
) -> TrainingReport:
    """
    Train the Random Forest and report cross-validated performance.

    Args:
        samples: Objects with ``name``/``node_name``, ``node_type``, ``label``.
        cv_folds: Stratified cross-validation folds.
        seed: Fixed for reproducibility.
        n_estimators: Trees in the forest.

    Returns:
        A :class:`TrainingReport`.

    Raises:
        ImportError: If scikit-learn is not installed.
        ValueError: If there are too few samples to cross-validate.
    """
    if not is_available():
        raise ImportError(
            "scikit-learn is required: pip install 'codeabstract[ml]'"
        )

    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    data = build_matrix(samples)
    X = np.array(data['X'], dtype=float)
    y = np.array(data['y'])

    if len(y) < cv_folds * 2:
        raise ValueError(
            f"need at least {cv_folds * 2} samples for {cv_folds}-fold CV, "
            f"got {len(y)}"
        )

    model = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=seed,
        class_weight='balanced',
        n_jobs=1,
    )
    splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
    predictions = cross_val_predict(model, X, y, cv=splitter)

    fold_accuracies = []
    for _, test_index in splitter.split(X, y):
        fold_accuracies.append(
            float((predictions[test_index] == y[test_index]).mean())
        )

    # Per-class F1
    per_class_f1: Dict[str, float] = {}
    for label in sorted(set(y)):
        true_positive = int(((predictions == label) & (y == label)).sum())
        false_positive = int(((predictions == label) & (y != label)).sum())
        false_negative = int(((predictions != label) & (y == label)).sum())
        precision = (
            true_positive / (true_positive + false_positive)
            if (true_positive + false_positive) else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if (true_positive + false_negative) else 0.0
        )
        per_class_f1[label] = round(
            2 * precision * recall / (precision + recall)
            if (precision + recall) else 0.0,
            4,
        )

    # Feature importances from a full-data fit
    model.fit(X, y)
    importances = sorted(
        zip(FEATURE_NAMES, (round(float(v), 4) for v in model.feature_importances_)),
        key=lambda pair: pair[1],
        reverse=True,
    )

    report = TrainingReport(
        n_samples=len(y),
        n_features=X.shape[1],
        cv_folds=cv_folds,
        cv_accuracy_mean=round(float(np.mean(fold_accuracies)), 4),
        cv_accuracy_std=round(float(np.std(fold_accuracies)), 4),
        per_class_f1=per_class_f1,
        feature_importances=importances,
    )

    _attach_integrity_checks(report, samples, predictions)
    return report


def _attach_integrity_checks(
    report: TrainingReport,
    samples: Sequence,
    predictions,
) -> None:
    """
    Measure whether this training run means anything.

    Two checks: how far the model merely reproduces the regex baseline,
    and how much of the dataset can discriminate between detectors at all.
    """
    from evaluation.benchmarks.annotation import AnnotatedNode, circularity_report
    from evaluation.metrics.detection import Sample, detector_regex

    baseline_predictions = [
        detector_regex(Sample(
            name=getattr(s, 'name', None) or getattr(s, 'node_name', ''),
            node_type=getattr(s, 'node_type', 'Name'),
            label=getattr(s, 'label', None) or getattr(s, 'expected_label', ''),
        ))
        for s in samples
    ]
    agreement = sum(
        1 for model_prediction, baseline in zip(predictions, baseline_predictions)
        if model_prediction == baseline
    ) / len(baseline_predictions)
    report.agreement_with_regex = round(agreement, 4)

    annotated = [
        AnnotatedNode(
            node_name=getattr(s, 'name', None) or getattr(s, 'node_name', ''),
            node_type=getattr(s, 'node_type', 'Name'),
            label=getattr(s, 'label', None) or getattr(s, 'expected_label', ''),
            rationale=getattr(s, 'rationale', '') or getattr(s, 'notes', ''),
            blind_to_patterns=getattr(s, 'blind_to_patterns', False),
            source=getattr(s, 'source', ''),
        )
        for s in samples
    ]
    audit = circularity_report(annotated)
    report.dataset_discriminative_power = audit.discriminative_power

    if agreement >= 0.90:
        report.warnings.append(
            f"The model reproduces the regex baseline on "
            f"{agreement:.1%} of samples. On a dataset labelled from those "
            f"regexes this is the expected outcome, not evidence of learning."
        )
    if not audit.is_usable:
        report.warnings.append(
            f"Dataset discriminative power is {audit.discriminative_power:.1%}; "
            f"it cannot separate this model from the baseline."
        )
    if audit.blind_fraction < 1.0:
        report.warnings.append(
            "Labels were not assigned blind to the pattern list, so this "
            "score cannot be reported as detector accuracy."
        )

    report.trustworthy = (
        audit.is_usable
        and audit.blind_fraction >= 1.0
        and agreement < 0.90
    )


def train_on_legacy_dataset() -> TrainingReport:
    """
    Train on the shipped 150-node dataset.

    Kept as a demonstration rather than an evaluation: it shows what
    training on circular labels produces, which is a model that agrees with
    the regexes almost everywhere.
    """
    from evaluation.benchmarks.annotation import load_legacy_dataset
    return train_and_report(load_legacy_dataset())
