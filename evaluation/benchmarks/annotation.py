"""
Annotation Schema and Dataset Integrity Tools

Phase 2 — the "de-circularise the dataset" workstream.

The audit found that `labeled_nodes.py` was labelled *from* the patterns it
is used to grade: its own justification column reads "Contains 'api_key'".
An F1 computed on such a dataset measures regex self-consistency, and it
cannot fall much below 1.0 no matter what the detector does.

This module provides:

* :class:`AnnotatedNode` — a schema that makes independence *recordable*:
  who labelled it, from what provenance, and whether they could see the
  pattern list while doing so.
* :func:`cohens_kappa` — inter-annotator agreement, so a dataset's
  reliability is reported rather than asserted.
* :func:`circularity_report` — the diagnostic. It measures how much of a
  dataset's ground truth is already determined by the detector under test,
  and reports the **discriminative power**: the fraction of items where a
  naive regex baseline is wrong. Items the baseline already gets right
  carry no information about whether a better detector is better.

The point of the last one is that circularity should be a number in the
report, not a claim in a document. A dataset with discriminative power near
zero cannot support any comparison, and saying so up front is cheaper than
publishing an F1 that means nothing.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

LABELS = ('SECRET', 'VALUE', 'IDENTIFIER')


@dataclass
class AnnotatedNode:
    """
    One labelled sample, with its provenance and annotation conditions.

    The fields that matter for integrity are the last three. A dataset
    where ``blind_to_patterns`` is False everywhere is, by construction,
    unable to grade the patterns.
    """

    node_name: str
    node_type: str
    label: str
    domain: str = ""
    source: str = ""              # where the sample came from
    annotator: str = ""           # who assigned the label
    blind_to_patterns: bool = False   # was the pattern list hidden?
    rationale: str = ""

    def __post_init__(self):
        if self.label not in LABELS:
            raise ValueError(
                f"label must be one of {LABELS}, got {self.label!r}"
            )


@dataclass
class AgreementReport:
    """Inter-annotator agreement for a dataset."""

    n_items: int
    observed_agreement: float
    expected_agreement: float
    kappa: float
    per_label_agreement: Dict[str, float] = field(default_factory=dict)

    @property
    def interpretation(self) -> str:
        """Landis & Koch's conventional reading of a kappa value."""
        k = self.kappa
        if k < 0.0:
            return "worse than chance"
        if k < 0.20:
            return "slight"
        if k < 0.40:
            return "fair"
        if k < 0.60:
            return "moderate"
        if k < 0.80:
            return "substantial"
        return "almost perfect"


def cohens_kappa(
    labels_a: Sequence[str],
    labels_b: Sequence[str],
) -> AgreementReport:
    """
    Cohen's κ between two annotators over the same items.

    κ corrects raw agreement for the agreement expected by chance, which
    matters here because the label distribution is skewed — two annotators
    who both guess IDENTIFIER most of the time will agree often while
    demonstrating nothing.

    Args:
        labels_a: First annotator's labels, item-aligned.
        labels_b: Second annotator's labels, item-aligned.

    Returns:
        An :class:`AgreementReport`.

    Raises:
        ValueError: If the two sequences differ in length or are empty.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(
            f"annotators labelled different numbers of items: "
            f"{len(labels_a)} vs {len(labels_b)}"
        )
    if not labels_a:
        raise ValueError("no items to compare")

    n = len(labels_a)
    agreements = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    observed = agreements / n

    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum(
        (counts_a.get(label, 0) / n) * (counts_b.get(label, 0) / n)
        for label in set(labels_a) | set(labels_b)
    )

    kappa = 1.0 if expected >= 1.0 else (observed - expected) / (1 - expected)

    per_label: Dict[str, float] = {}
    for label in set(labels_a) | set(labels_b):
        relevant = [
            (a, b) for a, b in zip(labels_a, labels_b)
            if a == label or b == label
        ]
        if relevant:
            per_label[label] = round(
                sum(1 for a, b in relevant if a == b) / len(relevant), 4
            )

    return AgreementReport(
        n_items=n,
        observed_agreement=round(observed, 4),
        expected_agreement=round(expected, 4),
        kappa=round(kappa, 4),
        per_label_agreement=per_label,
    )


@dataclass
class CircularityReport:
    """
    How much of a dataset's ground truth the detector already determines.

    ``discriminative_power`` is the figure that matters: the fraction of
    items where the naive baseline is wrong, and therefore the fraction
    that can tell two detectors apart. Everything else is context for it.
    """

    n_items: int
    baseline_accuracy: float
    discriminative_items: int
    discriminative_power: float
    rationale_leakage: float
    blind_fraction: float
    sourced_fraction: float
    notes: List[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """
        Whether this dataset can support a detector comparison at all.

        The 10% floor is a judgement call, not a standard: with fewer
        discriminative items than that, any difference between detectors
        rests on a handful of samples and will not survive a confidence
        interval.
        """
        return self.discriminative_power >= 0.10


def _baseline_predict(name: str, node_type: str, patterns_secret, patterns_value) -> str:
    """The naive name-regex classifier, used as the circularity yardstick."""
    text = name.lower()
    for pattern in patterns_secret:
        try:
            if re.search(pattern, text):
                return 'SECRET'
        except re.error:
            continue
    for pattern in patterns_value:
        try:
            if re.search(pattern, text):
                return 'VALUE'
        except re.error:
            continue
    if node_type == 'Constant':
        try:
            float(name)
            return 'VALUE'
        except ValueError:
            pass
    return 'IDENTIFIER'


def circularity_report(
    dataset: Sequence[AnnotatedNode],
    patterns_secret: Optional[Sequence[str]] = None,
    patterns_value: Optional[Sequence[str]] = None,
) -> CircularityReport:
    """
    Measure how far a dataset's labels are determined by the patterns.

    Args:
        dataset: The labelled samples.
        patterns_secret: SECRET patterns; defaults to the shipped list.
        patterns_value: VALUE patterns; defaults to the shipped list.

    Returns:
        A :class:`CircularityReport`.

    Raises:
        ValueError: If the dataset is empty.
    """
    if not dataset:
        raise ValueError("cannot audit an empty dataset")

    if patterns_secret is None or patterns_value is None:
        from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS
        patterns_secret = patterns_secret or SECRET_PATTERNS
        patterns_value = patterns_value or VALUE_PATTERNS

    n = len(dataset)
    correct = 0
    discriminative = 0

    for item in dataset:
        predicted = _baseline_predict(
            item.node_name, item.node_type, patterns_secret, patterns_value
        )
        if predicted == item.label:
            correct += 1
        else:
            discriminative += 1

    # A rationale that quotes the pattern it was derived from is direct
    # evidence the label was read off the regex rather than the sample.
    pattern_words = set()
    for pattern in list(patterns_secret) + list(patterns_value):
        for word in re.findall(r'[a-z_]{3,}', pattern):
            pattern_words.add(word)

    leaking = 0
    for item in dataset:
        rationale = item.rationale.lower()
        if not rationale:
            continue
        if any(f"'{word}'" in rationale or f'"{word}"' in rationale
               for word in pattern_words):
            leaking += 1
        elif 'contains' in rationale and any(w in rationale for w in pattern_words):
            leaking += 1

    blind = sum(1 for item in dataset if item.blind_to_patterns)
    sourced = sum(1 for item in dataset if item.source)

    report = CircularityReport(
        n_items=n,
        baseline_accuracy=round(correct / n, 4),
        discriminative_items=discriminative,
        discriminative_power=round(discriminative / n, 4),
        rationale_leakage=round(leaking / n, 4),
        blind_fraction=round(blind / n, 4),
        sourced_fraction=round(sourced / n, 4),
    )

    if report.baseline_accuracy >= 0.85:
        report.notes.append(
            f"The naive regex baseline already scores "
            f"{report.baseline_accuracy:.1%} on this dataset, so most items "
            f"cannot distinguish it from any other detector."
        )
    if report.rationale_leakage >= 0.25:
        report.notes.append(
            f"{report.rationale_leakage:.1%} of rationales quote the pattern "
            f"list, indicating labels were derived from the patterns under test."
        )
    if report.blind_fraction < 1.0:
        report.notes.append(
            f"Only {report.blind_fraction:.1%} of items were annotated blind "
            f"to the pattern list; independence cannot be assumed for the rest."
        )
    if report.sourced_fraction < 1.0:
        report.notes.append(
            f"Only {report.sourced_fraction:.1%} of items record a provenance, "
            f"so the sample cannot be traced to real-world code."
        )
    if not report.is_usable:
        report.notes.append(
            f"Discriminative power is {report.discriminative_power:.1%} "
            f"({report.discriminative_items} of {n} items). This dataset "
            f"cannot support a detector comparison."
        )

    return report


def load_legacy_dataset() -> List[AnnotatedNode]:
    """
    Load the pre-Phase-2 dataset into the annotation schema.

    Its integrity fields are filled in honestly: no provenance, no blind
    annotation, and the rationale carried through verbatim so the
    circularity audit can read it.
    """
    from evaluation.benchmarks.labeled_nodes import ALL_LABELED_NODES

    return [
        AnnotatedNode(
            node_name=item.node_name,
            node_type=item.node_type,
            label=item.expected_label,
            domain=item.domain,
            source="",                  # synthesised, not mined
            annotator="original-author",
            blind_to_patterns=False,    # author also wrote the patterns
            rationale=item.notes,
        )
        for item in ALL_LABELED_NODES
    ]
