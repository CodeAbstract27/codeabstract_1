"""
Regression: the PIR privacy metric's ground truth must not be context-blind.

Investigated and fixed per docs/PIR_GROUND_TRUTH_DECISION.md.
``evaluation.metrics.privacy._count_original_labels`` decided "what counts
as sensitive in the original source" using ``algorithms.classify.classify_node``
called on each AST node in isolation (``inherited=None``), instead of the
context-aware path (``core.context_features.analyze_context`` /
``inherited_secret_labels``, then ``classify_with_evidence``) production
abstraction actually uses to decide what to redact.

Measured impact: 7 of 7 known context-dependent secret fixtures were
under-counted by the old ground truth, including the plain control case
(a short, non-vendor-shaped literal bound to a secret-named variable) --
not an exotic edge case. On the real 10-file evaluation corpus, 13 literal
SECRET values across 4 files were classified SECRET by production only
through context and were invisible to the old ground truth's SECRET set
entirely. Production already redacts all of them correctly (0% actual
leakage in the corpus either way), but the old ground truth could not have
detected a *regression* in that redaction, because it never put those
values on its checklist in the first place.
"""

import pytest

from evaluation.metrics.privacy import _count_original_labels, evaluate_file_privacy


# (fixture source, name that must appear in the SECRET set)
CONTEXT_DEPENDENT_SECRETS = [
    (
        'value = "sk_live_abc123" + "def456ghi789jkl012"\nprint(value)\n',
        "sk_live_abc123",
    ),
    (
        'db_pass = "hunter" + "2222"\nprint(db_pass)\n',
        "hunter",
    ),
    (
        'db_pass = "hunter2"\nconn = f"postgres://admin:{db_pass}@10.2.3.4:5432/prod"\n',
        "hunter2",
    ),
    (
        'x = "db://%s:%s@host" % (user, "hunter2222")\n',
        "hunter2222",
    ),
    (
        'connect(password="hunter2222")\n',
        "hunter2222",
    ),
    (
        # The plain, unremarkable control case: a short, non-vendor-shaped
        # literal bound to an obviously secret-named variable. Its own
        # value-shape check (vendor format or 24+ chars of entropy) cannot
        # catch it; only context (the binding) can.
        'api_key = "hunter2222"\nprint(api_key)\n',
        "hunter2222",
    ),
]


class TestPIRGroundTruthIsContextAware:

    @pytest.mark.parametrize("source, must_be_secret", CONTEXT_DEPENDENT_SECRETS)
    def test_context_only_secret_value_is_counted(self, source, must_be_secret):
        labels = _count_original_labels(source)
        assert must_be_secret in labels["SECRET"], (
            f"{must_be_secret!r} was not in the ground-truth SECRET set for "
            f"{source!r} -- the PIR metric would never notice a regression "
            f"that leaked it, because it was never on the checklist"
        )

    def test_ordinary_name_only_secret_still_counted(self):
        """Regression guard: a name that matches a SECRET pattern on its
        own (no context needed) must still be counted, as before."""
        labels = _count_original_labels('STRIPE_API_KEY = "irrelevant"\n')
        assert "STRIPE_API_KEY" in labels["SECRET"]

    def test_ordinary_business_value_unaffected(self):
        """The fix must not sweep ordinary business values into SECRET."""
        labels = _count_original_labels('commission_rate = 0.029\n')
        assert "commission_rate" not in labels["SECRET"]

    def test_end_to_end_secret_total_reflects_context(self):
        """
        Before the fix, evaluate_file_privacy() reported secret_total=0 for
        this exact source at every privacy level -- not because nothing
        was sensitive, but because the ground truth never looked. Both
        fragments here are already correctly redacted by production; the
        metric must now say so for the right reason.
        """
        source = 'value = "sk_live_abc123" + "def456ghi789jkl012"\nprint(value)\n'
        for level in ("low", "medium", "high", "critical"):
            result = evaluate_file_privacy(source, "concat_test.py", privacy_level=level)
            assert result.secret_total == 2, (
                f"level={level}: expected both concatenated fragments to be "
                f"counted as SECRET in the ground truth, got secret_total="
                f"{result.secret_total}"
            )
            assert result.secret_leakage_rate == 0.0
