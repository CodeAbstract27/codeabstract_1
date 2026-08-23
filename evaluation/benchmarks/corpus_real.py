"""
Real-Code Benchmark Corpus

Phase 3 — the "corpus to 100+ files" workstream.

The original corpus is ten synthetic files of 31–48 LOC, written alongside
the tool by the same hand. That is too small for the proposal's 100+ sample
target, and too friendly: it contains no f-string secrets, no names shadowed
across scopes, and no file with more than ten variables — which is precisely
why three critical defects survived to the audit with a green dashboard.

This module builds a corpus from **real Python source already on this
machine**: the standard library, and any installed third-party packages.
That code was written by people with no knowledge of this project, which is
the property the synthetic corpus can never have.

What it is good for: structure preservation, mapping accuracy, performance,
and — most importantly — the linkage attack in :mod:`evaluation.adversary`,
which needs a large pool of *structurally similar* candidates to be a fair
test rather than a formality.

What it is not good for: leak testing. Stdlib code contains no credentials,
so ground truth for "did a secret survive" has to come from the synthetic
corpus, where the secrets are known by construction. The two corpora serve
different pillars and neither replaces the other.

Selection is deterministic — sorted by path, filtered by size — so the same
machine yields the same corpus on every run.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Files outside this range are excluded: very short files have no structure
# to measure, and very long ones dominate performance timings.
MIN_LOC = 50
MAX_LOC = 500

# Vendored copies, test fixtures and generated parsers are not
# representative of code someone would ask an LLM about.
_EXCLUDED_PARTS = {
    'test', 'tests', '__pycache__', 'site-packages', 'vendor', '_vendor',
    'idlelib', 'lib2to3', 'turtledemo', 'tkinter', 'encodings',
}


def _count_loc(source: str) -> int:
    """Non-blank, non-comment lines."""
    return sum(
        1 for line in source.splitlines()
        if line.strip() and not line.strip().startswith('#')
    )


def _is_eligible(path: Path) -> bool:
    """True if a path looks like ordinary application-style source."""
    if path.name.startswith('_') and path.name != '__init__.py':
        return False
    return not any(part in _EXCLUDED_PARTS for part in path.parts)


def discover_source_files(
    roots: Optional[List[Path]] = None,
    limit: int = 120,
    min_loc: int = MIN_LOC,
    max_loc: int = MAX_LOC,
) -> List[Dict]:
    """
    Collect real Python files from the local installation.

    Args:
        roots: Directories to search. Defaults to the standard library.
        limit: Maximum files to return.
        min_loc: Minimum lines of code.
        max_loc: Maximum lines of code.

    Returns:
        Corpus entries with ``name``, ``domain``, ``sensitivity``, ``loc``
        and ``code`` — the same shape as the synthetic corpus, so every
        existing metric consumes them unchanged.
    """
    if roots is None:
        roots = [Path(os.path.dirname(os.__file__))]

    collected: List[Dict] = []
    seen_names = set()

    for root in roots:
        if not root.is_dir():
            continue

        for path in sorted(root.rglob('*.py')):
            if len(collected) >= limit:
                break
            if not _is_eligible(path):
                continue

            try:
                source = path.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue

            loc = _count_loc(source)
            if not (min_loc <= loc <= max_loc):
                continue

            # Must parse on this interpreter to be usable as a benchmark.
            try:
                compile(source, str(path), 'exec', dont_inherit=True)
            except (SyntaxError, ValueError):
                continue

            name = path.stem
            if name in seen_names:
                name = f"{path.parent.name}_{path.stem}"
            if name in seen_names:
                continue
            seen_names.add(name)

            collected.append({
                'name': name,
                'domain': path.parent.name,
                'sensitivity': 'unknown',
                'loc': loc,
                'code': source,
                'origin': str(path),
            })

    return collected


_CACHE: Optional[List[Dict]] = None


def get_real_corpus(limit: int = 120) -> List[Dict]:
    """
    Return the real-code corpus, discovering it once per process.

    Args:
        limit: Maximum files.

    Returns:
        Corpus entries. Possibly empty if no source is readable, in which
        case callers should fall back to the synthetic corpus rather than
        failing — a missing corpus is a reason to report less, not to crash.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = discover_source_files(limit=limit)
    return _CACHE


def corpus_stats(files: Optional[List[Dict]] = None) -> Dict:
    """Summary statistics, for the report header."""
    if files is None:
        files = get_real_corpus()

    if not files:
        return {'total_files': 0, 'total_loc': 0, 'mean_loc': 0, 'domains': 0}

    total_loc = sum(entry['loc'] for entry in files)
    return {
        'total_files': len(files),
        'total_loc': total_loc,
        'mean_loc': round(total_loc / len(files), 1),
        'min_loc': min(entry['loc'] for entry in files),
        'max_loc': max(entry['loc'] for entry in files),
        'domains': len({entry['domain'] for entry in files}),
        'source': 'python-stdlib',
        'python_version': sys.version.split()[0],
    }


def combined_corpus(limit: int = 120) -> List[Dict]:
    """
    Synthetic (secret-bearing, known ground truth) plus real (structural).

    Kept as one list for metrics that only need volume; metrics that need
    known secrets should use the synthetic corpus directly.
    """
    from evaluation.benchmarks.corpus import ALL_FILES
    return list(ALL_FILES) + get_real_corpus(limit=limit)
