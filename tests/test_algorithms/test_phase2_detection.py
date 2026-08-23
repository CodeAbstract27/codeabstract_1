"""
Phase 2 detection regression suite.

Covers the usage-based context detector, the confidence-bearing hybrid
classifier, the dataset integrity tools, and the detector-comparison
harness.

The context tests are the substantive ones: every fixture uses an
identifier with **no** secret-ish name, so a name-regex scores zero on all
of them by construction. They are behavioural capability tests, not an
evaluation dataset — see `docs/UPGRADE_PLAN.md` Phase 2 on why this phase
ships no benchmark numbers for detector accuracy.
"""

import ast

import pytest

from algorithms.abstract import abstract
from algorithms.classify import Decision, classify_node, classify_with_evidence
from config.patterns import SECRET_PATTERNS
from core.context_features import analyze_context, inherited_secret_labels
from core.pattern_matcher import matches_any


def _redacted(source: str, identifier: str, level: str = "low") -> bool:
    """True if *identifier* does not survive abstraction."""
    return identifier not in abstract(source, privacy_level=level).abstract_code


# ═══════════════════════════════════════════════════════════
# Context features
# ═══════════════════════════════════════════════════════════

class TestContextDetection:
    """Usage signals must catch credentials a name-regex cannot see."""

    CASES = [
        ("env_subscript", 'import os\nblob = os.environ["STRIPE_LIVE"]\nsend(blob)\n', "blob"),
        ("env_getenv", 'import os\nblob = os.getenv("STRIPE_LIVE")\nsend(blob)\n', "blob"),
        ("auth_header", 'headers = {"Authorization": handle}\n', "handle"),
        ("secret_kwarg", 'conn = connect(host="db", password=material)\n', "material"),
        ("compare_digest", 'import hmac\nokay = hmac.compare_digest(supplied, other)\n', "supplied"),
        ("callee_signature", 'def store(api_key):\n    pass\nstore(payload)\n', "payload"),
        ("secret_source", 'material = vault.get_secret("n")\nuse(material)\n', "material"),
    ]

    @pytest.mark.parametrize("case,source,identifier", CASES)
    def test_name_gives_no_signal(self, case, source, identifier):
        """Precondition: a name-regex must score zero on every fixture."""
        assert not matches_any(identifier.lower(), SECRET_PATTERNS), (
            f"{case}: fixture is invalid — the name alone reveals the secret"
        )

    @pytest.mark.parametrize("case,source,identifier", CASES)
    def test_context_triggers_redaction(self, case, source, identifier):
        """Usage alone must be enough, even at the loosest privacy level."""
        assert _redacted(source, identifier), f"{case}: {identifier} survived"

    @pytest.mark.parametrize("source,identifier", [
        ('total_items = compute(rows)\n', 'rows'),
        ('result_set = query(table_name)\nrender(result_set)\n', 'result_set'),
        ('def handler(request):\n    return request\n', 'request'),
    ])
    def test_benign_code_is_not_over_redacted(self, source, identifier):
        """
        The control. Over-redaction costs utility for no privacy gain, and
        a detector that flags everything is not a detector.
        """
        assert not _redacted(source, identifier), (
            f"{identifier} was redacted with no sensitivity signal"
        )

    def test_evidence_is_recorded(self):
        tree = ast.parse('headers = {"Authorization": handle}\n')
        evidence = analyze_context(tree)
        assert any('auth_header' in e.signals for e in evidence.values())

    def test_signals_combine(self):
        """Independent signals should raise the score above either alone."""
        from core.context_features import ContextEvidence
        one = ContextEvidence(signals=['secret_return'])
        two = ContextEvidence(signals=['secret_return', 'secret_sink'])
        assert two.score > one.score
        assert two.score < 1.0, "no finite evidence should reach certainty"

    def test_inherited_labels_respect_threshold(self):
        from core.context_features import ContextEvidence
        weak = {1: ContextEvidence(signals=['secret_return'])}
        strong = {2: ContextEvidence(signals=['secret_kwarg'])}
        assert 1 not in inherited_secret_labels(weak)
        assert 2 in inherited_secret_labels(strong)

    def test_evidence_pools_across_occurrences(self):
        """
        A symbol is a credential because of what happens to it anywhere.
        Marking only the assignment target let later uses leak.
        """
        source = 'material = vault.get_secret("n")\nlog_line(material)\n'
        assert _redacted(source, 'material')


# ═══════════════════════════════════════════════════════════
# Confidence-bearing classification
# ═══════════════════════════════════════════════════════════

class TestHybridConfidence:
    """Decisions must carry a confidence and a reason."""

    def test_credential_format_is_most_confident(self):
        node = ast.Constant(value="sk_live_51H8xQ2eZvKYlo2C")
        decision = classify_with_evidence(node)
        assert decision.label == 'SECRET'
        assert decision.detector == 'credential-format'
        assert decision.confidence >= 0.95

    def test_name_pattern_is_less_confident_than_format(self):
        formatted = classify_with_evidence(ast.Constant(value="sk_live_51H8xQ2eZvKYlo2C"))
        named = classify_with_evidence(ast.Name(id="api_key", ctx=ast.Load()))
        assert named.confidence < formatted.confidence
        assert named.label == 'SECRET'

    def test_default_decision_is_low_confidence(self):
        decision = classify_with_evidence(ast.Name(id="widget", ctx=ast.Load()))
        assert decision.label == 'IDENTIFIER'
        assert decision.detector == 'default'

    def test_every_decision_carries_evidence(self):
        for node in (
            ast.Name(id="api_key", ctx=ast.Load()),
            ast.Name(id="widget", ctx=ast.Load()),
            ast.Constant(value=42),
        ):
            assert classify_with_evidence(node).evidence

    def test_describe_is_readable(self):
        text = classify_with_evidence(ast.Name(id="api_key", ctx=ast.Load())).describe()
        assert 'SECRET' in text

    def test_needs_review_flag(self):
        assert Decision('IDENTIFIER', 0.4, 'x').needs_review
        assert not Decision('SECRET', 0.99, 'x').needs_review

    def test_legacy_classify_node_unchanged(self):
        """The bare-label API must keep working for existing callers."""
        assert classify_node(ast.Name(id="api_key", ctx=ast.Load())) == 'SECRET'
        assert classify_node(ast.Name(id="widget", ctx=ast.Load())) == 'IDENTIFIER'

    def test_statistics_count_low_confidence(self):
        result = abstract("widget_name = other_thing\n", privacy_level="high")
        assert 'low_confidence_nodes' in result.statistics

    def test_mapping_records_detector_and_confidence(self):
        from algorithms.encrypt import decrypt_mapping
        result = abstract('api_key = "sk_live_51H8xQ2eZvKYlo2C"\n', privacy_level="low")
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
        assert any('confidence' in e and 'detector' in e for e in mapping.values())


# ═══════════════════════════════════════════════════════════
# Dataset integrity
# ═══════════════════════════════════════════════════════════

class TestDatasetIntegrity:
    """The circularity audit must detect circularity."""

    def test_kappa_perfect_agreement(self):
        from evaluation.benchmarks.annotation import cohens_kappa
        labels = ['SECRET', 'VALUE', 'IDENTIFIER', 'SECRET']
        assert cohens_kappa(labels, labels).kappa == 1.0

    def test_kappa_rejects_mismatched_lengths(self):
        from evaluation.benchmarks.annotation import cohens_kappa
        with pytest.raises(ValueError):
            cohens_kappa(['SECRET'], ['SECRET', 'VALUE'])

    def test_kappa_chance_agreement_is_near_zero(self):
        from evaluation.benchmarks.annotation import cohens_kappa
        a = ['SECRET', 'VALUE'] * 20
        b = ['SECRET', 'VALUE'] * 10 + ['VALUE', 'SECRET'] * 10
        assert abs(cohens_kappa(a, b).kappa) < 0.30

    def test_legacy_dataset_is_flagged_as_circular(self):
        from evaluation.benchmarks.annotation import (
            circularity_report, load_legacy_dataset,
        )
        audit = circularity_report(load_legacy_dataset())
        assert audit.baseline_accuracy >= 0.85, (
            "the regex baseline should already ace this dataset"
        )
        assert audit.rationale_leakage > 0.5, (
            "rationales quote the pattern list"
        )
        assert audit.blind_fraction == 0.0
        assert audit.sourced_fraction == 0.0
        assert audit.notes

    def test_annotation_schema_rejects_bad_label(self):
        from evaluation.benchmarks.annotation import AnnotatedNode
        with pytest.raises(ValueError):
            AnnotatedNode(node_name="x", node_type="Name", label="NONSENSE")

    def test_empty_dataset_rejected(self):
        from evaluation.benchmarks.annotation import circularity_report
        with pytest.raises(ValueError):
            circularity_report([])


# ═══════════════════════════════════════════════════════════
# Detector comparison harness
# ═══════════════════════════════════════════════════════════

class TestDetectionHarness:
    """Comparisons must report intervals, not just point estimates."""

    def test_scores_a_perfect_detector(self):
        from evaluation.metrics.detection import score_predictions
        truth = ['SECRET', 'VALUE', 'IDENTIFIER']
        score = score_predictions("perfect", truth, truth)
        assert score.accuracy == 1.0
        assert score.macro_f1 == 1.0

    def test_identical_detectors_have_zero_interval(self):
        from evaluation.metrics.detection import paired_bootstrap
        truth = ['SECRET', 'VALUE'] * 20
        comparison = paired_bootstrap(truth, truth, truth, n_bootstrap=200)
        assert comparison.difference == 0.0
        assert not comparison.significant

    def test_clearly_better_detector_is_significant(self):
        from evaluation.metrics.detection import paired_bootstrap
        truth = ['SECRET'] * 50 + ['IDENTIFIER'] * 50
        bad = ['IDENTIFIER'] * 100
        comparison = paired_bootstrap(
            truth, bad, truth, metric='macro_f1', n_bootstrap=300,
        )
        assert comparison.difference > 0
        assert comparison.significant

    def test_legacy_dataset_cannot_exercise_context(self):
        """
        The structural finding: node-level samples carry no surrounding
        code, so the context tier has nothing to read.
        """
        from evaluation.metrics.detection import (
            compare_on_dataset, samples_from_legacy,
        )
        result = compare_on_dataset(samples_from_legacy(), n_bootstrap=100)
        assert result['context_available'] is False

    def test_code_level_sample_enables_context(self):
        from evaluation.metrics.detection import Sample, detector_hybrid, detector_regex
        sample = Sample(
            name="handle",
            node_type="Name",
            label="SECRET",
            code='headers = {"Authorization": handle}\n',
        )
        assert sample.has_context
        assert detector_regex(sample) == 'IDENTIFIER'
        assert detector_hybrid(sample) == 'SECRET'

    def test_unknown_metric_rejected(self):
        from evaluation.metrics.detection import paired_bootstrap
        with pytest.raises(ValueError):
            paired_bootstrap(['SECRET'], ['SECRET'], ['SECRET'], metric='nope')


# ═══════════════════════════════════════════════════════════
# ML baseline
# ═══════════════════════════════════════════════════════════

class TestRandomForestBaseline:
    """The RF must refuse to present circular results as an evaluation."""

    def test_feature_vector_matches_declared_names(self):
        from ml.features import FEATURE_NAMES, extract_features
        assert len(extract_features("api_key", "Name")) == len(FEATURE_NAMES)

    def test_features_are_deterministic(self):
        from ml.features import extract_features
        assert extract_features("token_value") == extract_features("token_value")

    def test_features_exclude_the_patterns_under_test(self):
        """
        Feeding the model its own labelling rule would make its score
        meaningless on a dataset labelled by that rule.
        """
        from ml.features import FEATURE_NAMES
        for name in FEATURE_NAMES:
            assert 'secret_pattern' not in name
            assert 'regex' not in name

    @pytest.mark.skipif(
        not __import__('importlib.util', fromlist=['util']).find_spec('sklearn'),
        reason="scikit-learn not installed",
    )
    def test_training_flags_untrustworthy_dataset(self):
        from ml.random_forest import train_on_legacy_dataset
        report = train_on_legacy_dataset()
        assert report.n_samples == 150
        assert report.trustworthy is False, (
            "a dataset labelled from the patterns cannot yield a "
            "trustworthy detector score"
        )
        assert report.warnings

    def test_training_rejects_tiny_dataset(self):
        pytest.importorskip("sklearn")
        from evaluation.benchmarks.annotation import AnnotatedNode
        from ml.random_forest import train_and_report
        tiny = [
            AnnotatedNode(node_name="a", node_type="Name", label="SECRET"),
            AnnotatedNode(node_name="b", node_type="Name", label="VALUE"),
        ]
        with pytest.raises(ValueError):
            train_and_report(tiny)
