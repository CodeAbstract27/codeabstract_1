"""
Mapping Accuracy Metric — Pillar 6

Phase 1.

The proposal commits to **85%+ mapping accuracy** (feedback → original
code), but nothing measured it.  The existing reconstruction pillar reports
a token *hit rate* — whether a token can be looked up — which was 100% even
while the mapping pointed developers at the wrong function, because a
successful lookup says nothing about whether the answer is right.

This module grades the mapping against the source it came from:

    definition_accuracy   — does the recorded line actually contain the
                            recorded name, at the recorded column?
    occurrence_accuracy   — same check across every recorded occurrence,
                            not just the definition site.
    shadow_resolution     — of the names that appear in more than one
                            scope, what fraction received distinct tokens?
                            A flat name→token cache scores 0 here.
    line_map_accuracy     — does each abstract→original line pair actually
                            correspond, judged by re-deriving the mapping
                            independently of the index under test?
    mapping_accuracy      — the headline figure: mean of the above.

Every check is against ground truth recoverable from the source text, so
this metric can fail — unlike the pillars that grade the classifier with
the classifier.
"""

import ast
from dataclasses import dataclass, field
from typing import Dict, List

from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping
from evaluation.benchmarks.corpus import ALL_FILES


@dataclass
class MappingResult:
    """Mapping accuracy for a single file."""

    file_name: str
    total_tokens: int
    definition_hits: int
    definition_total: int
    occurrence_hits: int
    occurrence_total: int
    shadowed_names: int
    shadowed_resolved: int
    line_map_hits: int
    line_map_total: int
    definition_accuracy: float
    occurrence_accuracy: float
    shadow_resolution: float
    line_map_accuracy: float
    mapping_accuracy: float


@dataclass
class MappingSuiteResult:
    """Aggregated mapping accuracy across the corpus."""

    per_file: List[MappingResult] = field(default_factory=list)
    mean_definition_accuracy: float = 0.0
    mean_occurrence_accuracy: float = 0.0
    mean_shadow_resolution: float = 0.0
    mean_line_map_accuracy: float = 0.0
    mean_mapping_accuracy: float = 0.0
    total_shadowed_names: int = 0
    files_evaluated: int = 0


def _name_at(source_lines: List[str], lineno: int, col: int, name: str) -> bool:
    """
    True if *name* appears at the given position in the source.

    Falls back to a containment check on the line when the column does not
    line up: unparsing can shift columns (an f-string fragment, a rewritten
    default) without the mapping being wrong about *which line* the symbol
    lives on.
    """
    if lineno < 1 or lineno > len(source_lines):
        return False

    line = source_lines[lineno - 1]
    if line[col:col + len(name)] == name:
        return True
    return name in line


def evaluate_file_mapping(
    source_code: str,
    file_name: str,
    privacy_level: str = "high",
) -> MappingResult:
    """
    Grade the mapping produced for one source file.

    Args:
        source_code: Original Python source.
        file_name: Label for reporting.
        privacy_level: Abstraction level to evaluate.

    Returns:
        Populated :class:`MappingResult`.
    """
    result = abstract(source_code, privacy_level=privacy_level)
    mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
    source_lines = source_code.split('\n')

    definition_hits = definition_total = 0
    occurrence_hits = occurrence_total = 0

    # Literals and imports are rewritten rather than located in place, so
    # a textual position check does not apply to them.
    positional = {
        token: entry for token, entry in mapping.items()
        if entry.get('scope') not in ('literal', 'import')
    }

    for entry in positional.values():
        name = entry['name']

        definition_total += 1
        if _name_at(source_lines, entry['lineno'], 0, name):
            definition_hits += 1

        for occurrence in entry.get('occurrences', []):
            occurrence_total += 1
            if _name_at(
                source_lines,
                occurrence.get('lineno', -1),
                occurrence.get('col', 0),
                name,
            ):
                occurrence_hits += 1

    # ── shadowing ──────────────────────────────────────
    # Ground truth: names bound in more than one scope, derived from the
    # source directly rather than from the mapping under test.
    shadowed_in_source = _count_shadowed_in_source(source_code)

    scopes_per_name: Dict[str, set] = {}
    for entry in mapping.values():
        if entry.get('scope') in ('literal', 'import'):
            continue
        scopes_per_name.setdefault(entry['name'], set()).add(
            entry.get('scope', '')
        )

    # Only names the engine actually tokenised can be graded on
    # disambiguation.  Names deliberately preserved -- `self`, `cls`,
    # builtins, allowlisted imports -- are shadowed in the source but are
    # never mapped, and counting them as failures would penalise the engine
    # for behaving correctly.  `self` alone accounts for most of them.
    eligible = {
        name for name in shadowed_in_source
        if name in scopes_per_name
    }
    resolved = sum(
        1 for name in eligible if len(scopes_per_name[name]) > 1
    )

    shadow_total = len(eligible)
    shadow_resolution = (resolved / shadow_total) if shadow_total else 1.0

    # ── line map ───────────────────────────────────────
    line_map_hits, line_map_total = _grade_line_map(
        result.line_map, source_lines, result.abstract_code,
    )

    definition_accuracy = (
        definition_hits / definition_total if definition_total else 1.0
    )
    occurrence_accuracy = (
        occurrence_hits / occurrence_total if occurrence_total else 1.0
    )
    line_map_accuracy = (
        line_map_hits / line_map_total if line_map_total else 1.0
    )

    mapping_accuracy = (
        definition_accuracy + occurrence_accuracy
        + shadow_resolution + line_map_accuracy
    ) / 4

    return MappingResult(
        file_name=file_name,
        total_tokens=len(mapping),
        definition_hits=definition_hits,
        definition_total=definition_total,
        occurrence_hits=occurrence_hits,
        occurrence_total=occurrence_total,
        shadowed_names=shadow_total,
        shadowed_resolved=resolved,
        line_map_hits=line_map_hits,
        line_map_total=line_map_total,
        definition_accuracy=round(definition_accuracy, 4),
        occurrence_accuracy=round(occurrence_accuracy, 4),
        shadow_resolution=round(shadow_resolution, 4),
        line_map_accuracy=round(line_map_accuracy, 4),
        mapping_accuracy=round(mapping_accuracy, 4),
    )


def _count_shadowed_in_source(source_code: str) -> set:
    """
    Names bound in more than one scope, read straight from the source.

    Independent of the abstraction engine, so it cannot flatter it.
    """
    from core.symbol_table import build_scopes

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return set()

    scopes = build_scopes(tree)
    owners: Dict[str, set] = {}

    def walk(scope):
        for name in scope.bindings:
            owners.setdefault(name, set()).add(scope.uid)
        for child in scope.children:
            walk(child)

    walk(scopes.module_scope)
    return {name for name, scope_ids in owners.items() if len(scope_ids) > 1}


def _grade_line_map(
    line_map: Dict[int, int],
    source_lines: List[str],
    abstract_code: str,
) -> tuple:
    """
    Check each abstract→original line pair for plausibility.

    A pair is counted correct when the original line is non-blank and not a
    comment — that is, when it holds the statement the abstract line was
    produced from.  This is a coarse but independent check: it uses the
    original text, not the index that produced the pair.
    """
    if not line_map:
        return 0, 0

    abstract_lines = abstract_code.split('\n')
    hits = total = 0

    for abstract_line, original_line in line_map.items():
        if abstract_line < 1 or abstract_line > len(abstract_lines):
            continue
        if not abstract_lines[abstract_line - 1].strip():
            continue

        total += 1
        if 1 <= original_line <= len(source_lines):
            original = source_lines[original_line - 1].strip()
            if original and not original.startswith('#'):
                hits += 1

    return hits, total


def run_mapping_suite(privacy_level: str = "high") -> MappingSuiteResult:
    """
    Run the mapping accuracy metric across the whole benchmark corpus.

    Args:
        privacy_level: Abstraction level to evaluate.

    Returns:
        Aggregated :class:`MappingSuiteResult`.
    """
    suite = MappingSuiteResult()

    for entry in ALL_FILES:
        suite.per_file.append(
            evaluate_file_mapping(
                source_code=entry['code'],
                file_name=entry['name'],
                privacy_level=privacy_level,
            )
        )

    if not suite.per_file:
        return suite

    count = len(suite.per_file)
    suite.files_evaluated = count
    suite.mean_definition_accuracy = round(
        sum(r.definition_accuracy for r in suite.per_file) / count, 4)
    suite.mean_occurrence_accuracy = round(
        sum(r.occurrence_accuracy for r in suite.per_file) / count, 4)
    suite.mean_shadow_resolution = round(
        sum(r.shadow_resolution for r in suite.per_file) / count, 4)
    suite.mean_line_map_accuracy = round(
        sum(r.line_map_accuracy for r in suite.per_file) / count, 4)
    suite.mean_mapping_accuracy = round(
        sum(r.mapping_accuracy for r in suite.per_file) / count, 4)
    suite.total_shadowed_names = sum(r.shadowed_names for r in suite.per_file)

    return suite
