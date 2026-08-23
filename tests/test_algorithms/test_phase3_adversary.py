"""
Phase 3 adversarial-evaluation regression suite.

Covers the linkage attack, Code Privacy Entropy, alignment channels, token
prefix leakage, the real-code corpus, the historical regression harness,
and the utility-measurement scaffolding.

The most important test here is
``TestRegressionHarness::test_probes_fire_on_broken_code``: it asserts that
the evaluation goes red against a commit known to be broken. An evaluation
that has never failed is not known to be capable of failing, and that was
the central finding of the original audit.
"""

import ast

import pytest

from evaluation.adversary import (
    code_privacy_entropy,
    fingerprint,
    inventory_alignment_channels,
    measure_prefix_leakage,
    run_linkage_attack,
)

SIMPLE_FILES = [
    {'name': 'alpha', 'code': 'def alpha(a):\n    return a + 1\n'},
    {'name': 'beta', 'code': (
        'class Beta:\n'
        '    def run(self, x):\n'
        '        for i in range(x):\n'
        '            if i > 2:\n'
        '                return i\n'
        '        return 0\n'
    )},
    {'name': 'gamma', 'code': (
        'import os\n'
        'def gamma(values):\n'
        '    total = 0\n'
        '    while values:\n'
        '        total += values.pop()\n'
        '    try:\n'
        '        return total / len(values)\n'
        '    except ZeroDivisionError:\n'
        '        return 0\n'
    )},
]


# ═══════════════════════════════════════════════════════════
# Fingerprinting
# ═══════════════════════════════════════════════════════════

class TestFingerprint:
    """Fingerprints must capture structure and ignore identity."""

    def test_renaming_does_not_change_the_fingerprint(self):
        a = fingerprint('def alpha(data):\n    return data + 1\n')
        b = fingerprint('def FUNC_0(VAR_0):\n    return VAR_0 + NUM_0\n')
        assert a.node_sequence == b.node_sequence
        assert a.similarity(b) > 0.9

    def test_different_structure_scores_lower(self):
        a = fingerprint('def f(x):\n    return x\n')
        b = fingerprint(
            'class C:\n'
            '    def g(self):\n'
            '        for i in range(3):\n'
            '            if i:\n'
            '                pass\n'
        )
        assert a.similarity(b) < 0.5

    def test_unparseable_source_is_empty(self):
        assert fingerprint('def broken(:').node_sequence == []

    def test_empty_fingerprint_similarity_is_zero(self):
        assert fingerprint('def broken(:').similarity(
            fingerprint('def f(x):\n    return x\n')
        ) == 0.0

    def test_self_similarity_is_one(self):
        f = fingerprint(SIMPLE_FILES[2]['code'])
        assert f.similarity(f) == pytest.approx(1.0, abs=1e-6)


# ═══════════════════════════════════════════════════════════
# Code Privacy Entropy
# ═══════════════════════════════════════════════════════════

class TestCodePrivacyEntropy:
    """CPE must be 1 when the attacker knows nothing, 0 when certain."""

    def test_uniform_posterior_is_maximum_entropy(self):
        assert code_privacy_entropy([0.25] * 4) == pytest.approx(1.0)

    def test_point_mass_is_zero_entropy(self):
        assert code_privacy_entropy([1.0, 0.0, 0.0, 0.0]) == pytest.approx(0.0)

    def test_single_candidate_is_zero(self):
        assert code_privacy_entropy([1.0]) == 0.0

    def test_skewed_posterior_is_between(self):
        value = code_privacy_entropy([0.7, 0.1, 0.1, 0.1])
        assert 0.0 < value < 1.0


# ═══════════════════════════════════════════════════════════
# Linkage
# ═══════════════════════════════════════════════════════════

class TestLinkageAttack:
    """The attack must actually attack."""

    def test_requires_multiple_candidates(self):
        with pytest.raises(ValueError):
            run_linkage_attack([SIMPLE_FILES[0]])

    def test_structure_identifies_the_source(self):
        """
        The headline Phase 3 finding: abstraction preserves structure, and
        structure alone re-identifies the file.
        """
        report = run_linkage_attack(SIMPLE_FILES, privacy_level="high")
        assert report.top1_accuracy == 1.0
        assert report.advantage > 0.9
        assert report.code_privacy_entropy < 0.5

    def test_privacy_level_does_not_help(self):
        """
        Privacy levels govern identifier abstraction, not structure, so
        raising the level buys nothing against a linkage attack. Recording
        this is the point: the trade-off curve is flat along this axis.
        """
        scores = {
            level: run_linkage_attack(SIMPLE_FILES, privacy_level=level).top1_accuracy
            for level in ("low", "high", "critical")
        }
        assert len(set(scores.values())) == 1, (
            f"expected the attack to be unaffected by level, got {scores}"
        )

    def test_report_fields_are_consistent(self):
        report = run_linkage_attack(SIMPLE_FILES)
        assert report.n_files == len(SIMPLE_FILES)
        # Reported values are rounded to 4dp for the tables.
        assert report.random_baseline == pytest.approx(
            1 / len(SIMPLE_FILES), abs=1e-4
        )
        assert len(report.per_file) == len(SIMPLE_FILES)
        for result in report.per_file:
            assert 1 <= result.rank <= len(SIMPLE_FILES)
            assert result.posterior
            assert sum(result.posterior) == pytest.approx(1.0, abs=1e-6)

    def test_verdict_is_reported(self):
        assert run_linkage_attack(SIMPLE_FILES).verdict()


# ═══════════════════════════════════════════════════════════
# Alignment channels and prefix leakage
# ═══════════════════════════════════════════════════════════

class TestLeakageChannels:
    """Text that survives abstraction is an anchor for the attacker."""

    def test_survival_rate_drops_with_privacy_level(self):
        from algorithms.abstract import abstract
        source = SIMPLE_FILES[2]['code']

        low = inventory_alignment_channels(
            source, abstract(source, privacy_level="low").abstract_code
        ).survival_rate
        high = inventory_alignment_channels(
            source, abstract(source, privacy_level="high").abstract_code
        ).survival_rate
        assert high <= low

    def test_stdlib_imports_are_recorded_as_surviving(self):
        from algorithms.abstract import abstract
        source = "import os\nvalue_here = os.getcwd()\n"
        channels = inventory_alignment_channels(
            source, abstract(source, privacy_level="high").abstract_code
        )
        assert 'os' in channels.surviving_imports

    def test_prefix_leakage_counts_secret_positions(self):
        leakage = measure_prefix_leakage("SECRET_0 = CONST_1\nVAR_0 = SECRET_0\n")
        assert leakage.secret_positions_revealed == 2
        assert leakage.reveals_secret_locations
        assert leakage.n_tokens == 4

    def test_prefix_leakage_on_clean_code(self):
        leakage = measure_prefix_leakage("x = 1\n")
        assert leakage.n_tokens == 0
        assert not leakage.reveals_secret_locations


# ═══════════════════════════════════════════════════════════
# Real corpus
# ═══════════════════════════════════════════════════════════

class TestRealCorpus:
    """The corpus must be real code, and big enough to matter."""

    def test_corpus_meets_the_hundred_file_target(self):
        from evaluation.benchmarks.corpus_real import corpus_stats, get_real_corpus
        corpus = get_real_corpus()
        if not corpus:
            pytest.skip("no readable stdlib source on this machine")
        stats = corpus_stats(corpus)
        assert stats['total_files'] >= 100
        assert stats['mean_loc'] >= 50

    def test_every_file_parses(self):
        from evaluation.benchmarks.corpus_real import get_real_corpus
        corpus = get_real_corpus()
        if not corpus:
            pytest.skip("no readable stdlib source on this machine")
        for entry in corpus[:25]:
            ast.parse(entry['code'])

    def test_entries_match_the_synthetic_corpus_shape(self):
        from evaluation.benchmarks.corpus_real import get_real_corpus
        corpus = get_real_corpus()
        if not corpus:
            pytest.skip("no readable stdlib source on this machine")
        for key in ('name', 'domain', 'sensitivity', 'loc', 'code'):
            assert key in corpus[0]

    def test_discovery_is_deterministic(self):
        from evaluation.benchmarks.corpus_real import discover_source_files
        first = [e['name'] for e in discover_source_files(limit=15)]
        second = [e['name'] for e in discover_source_files(limit=15)]
        assert first == second


# ═══════════════════════════════════════════════════════════
# Historical regression harness
# ═══════════════════════════════════════════════════════════

class TestRegressionHarness:
    """The suite must be demonstrably capable of failing."""

    def test_probes_stay_quiet_on_current_code(self):
        from evaluation.regression_harness import run_against_working_tree
        report = run_against_working_tree()
        assert report.errors == 0, report.summary()
        assert report.defects_found == 0, report.summary()

    def test_probes_fire_on_broken_code(self):
        """
        Exit criterion: run against the pre-fix commit, the probes must go
        red. If they do not, the probes are wrong, not the commit.
        """
        import subprocess
        from evaluation.regression_harness import run_against_commit

        available = subprocess.run(
            ["git", "cat-file", "-e", "47d91bc^{commit}"],
            capture_output=True, check=False,
        )
        if available.returncode != 0:
            pytest.skip("pre-fix commit 47d91bc not present in this clone")

        report = run_against_commit("47d91bc")
        assert report.defects_found >= 4, report.summary()

    def test_summary_is_readable(self):
        from evaluation.regression_harness import run_against_working_tree
        assert "defects present" in run_against_working_tree().summary()


# ═══════════════════════════════════════════════════════════
# Utility scaffolding
# ═══════════════════════════════════════════════════════════

class TestUtilityHarness:
    """Collection is automated; quality judgement is not faked."""

    def test_collection_refuses_without_a_client(self):
        """
        A utility number nobody measured is worse than a missing one.
        """
        from evaluation.utility import collect_pairs
        with pytest.raises(ValueError, match="requires an LLM client"):
            collect_pairs(SIMPLE_FILES, client=None)

    def test_identical_responses_score_perfectly(self):
        from evaluation.utility import ResponsePair, score_pair
        text = "There is a bug on line 3 and a security issue on line 5."
        scores = score_pair(ResponsePair('f', 'review', text, text))
        assert scores.issue_overlap == 1.0
        assert scores.line_citation_agreement == 1.0

    def test_empty_abstract_response_scores_zero_overlap(self):
        from evaluation.utility import ResponsePair, score_pair
        scores = score_pair(ResponsePair('f', 'review', "A bug on line 2.", ""))
        assert scores.abstract_is_empty
        assert scores.issue_overlap == 0.0

    def test_line_map_aligns_citations(self):
        from evaluation.utility import ResponsePair, score_pair
        pair = ResponsePair('f', 'review', "Bug on line 9.", "Bug on line 3.")
        without = score_pair(pair)
        with_map = score_pair(pair, line_map={3: 9})
        assert without.line_citation_agreement == 0.0
        assert with_map.line_citation_agreement == 1.0

    def test_cache_round_trips(self, tmp_path):
        from evaluation.utility import ResponseCache
        cache = ResponseCache(tmp_path)
        assert cache.get("prompt", "model") is None
        cache.put("prompt", "model", "answer")
        assert cache.get("prompt", "model") == "answer"

    def test_rating_sheet_is_blind(self, tmp_path):
        from evaluation.utility import ResponsePair, export_rating_sheet
        import json

        pairs = [ResponsePair('f1', 'review', 'raw text', 'abstract text')]
        paths = export_rating_sheet(pairs, tmp_path)

        sheet = json.loads(paths['sheet'].read_text(encoding='utf-8'))
        key = json.loads(paths['key'].read_text(encoding='utf-8'))

        assert len(sheet) == 2
        for item in sheet:
            assert 'variant' not in item, "the sheet must not reveal the condition"
            assert 'file_name' not in item
        assert {entry['variant'] for entry in key} == {'raw', 'abstract'}

    def test_scoring_requires_pairs(self):
        from evaluation.utility import score_pairs
        with pytest.raises(ValueError):
            score_pairs([])
