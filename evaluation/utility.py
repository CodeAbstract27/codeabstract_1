"""
Privacy–Utility Measurement

Phase 3 — the "utility measurement" workstream.

The proposal targets **80% utility preservation** and the audit found no
instrument for it at all: nothing in the suite asks whether an LLM given
abstracted code is still able to help. Every pillar measured privacy or
correctness; the other half of the trade-off went unmeasured.

The design here is the standard paired comparison: ask the *same question*
of the raw file and the abstracted file, then compare the answers. What that
comparison cannot do by itself is judge quality — deciding whether an answer
is *correct and actionable* is a human judgement, and the proposal is right
to specify blind rating for it.

So this module splits the job:

* **Collection** is automated and reproducible. Responses are cached
  content-addressed on disk, so a run costs nothing the second time and a
  reviewer can reproduce every number from the committed fixtures without
  an API key.
* **Automatic proxies** are computed — issue-overlap, line-citation
  agreement, response-length ratio. These are genuinely informative and
  genuinely not a quality score.
* **Blind rating** is prepared, not faked: :func:`export_rating_sheet`
  writes a shuffled, anonymised sheet for human raters, with the
  raw/abstracted assignment held in a separate key file.

Calling this without an LLM client raises rather than returning zeros: a
utility number nobody measured is worse than a missing one.
"""

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_QUESTIONS = {
    'debug': "Find bugs and errors in this code.",
    'review': "Review this code for quality and issues.",
    'optimize': "Suggest optimizations for this code.",
    'security': "Find security issues in this code.",
    'explain': "Explain what this code does.",
}


@dataclass
class ResponsePair:
    """The LLM's answers to one question, raw versus abstracted."""

    file_name: str
    task: str
    raw_response: str
    abstract_response: str
    raw_cached: bool = False
    abstract_cached: bool = False


@dataclass
class UtilityScores:
    """Automatic proxies for one response pair."""

    file_name: str
    task: str
    issue_overlap: float          # shared findings / findings on raw
    line_citation_agreement: float
    length_ratio: float
    abstract_is_empty: bool

    @property
    def composite(self) -> float:
        """
        Unweighted mean of the proxies.

        Deliberately *not* called a utility score. It correlates with
        usefulness but does not measure it, and presenting it as the
        headline figure would repeat the mistake this phase exists to fix.
        """
        return round(
            (self.issue_overlap + self.line_citation_agreement
             + min(self.length_ratio, 1.0)) / 3,
            4,
        )


@dataclass
class UtilityReport:
    """Aggregated proxies across a corpus."""

    privacy_level: str
    n_pairs: int
    mean_issue_overlap: float
    mean_line_agreement: float
    mean_length_ratio: float
    mean_composite: float
    per_file: List[UtilityScores] = field(default_factory=list)
    cache_hits: int = 0
    api_calls: int = 0

    def caveat(self) -> str:
        return (
            "These are automatic proxies, not a utility score. The "
            "proposal's 80% target requires blind human rating; use "
            "export_rating_sheet() to prepare it."
        )


class ResponseCache:
    """
    Content-addressed on-disk cache of LLM responses.

    Keyed by the hash of (prompt, model), so a committed cache makes every
    number in the report reproducible without an API key — which is the
    difference between a result a reviewer can check and one they have to
    take on trust.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, prompt: str, model: str) -> Path:
        digest = hashlib.sha256(f"{model}\x00{prompt}".encode('utf-8')).hexdigest()
        return self.directory / f"{digest}.json"

    def get(self, prompt: str, model: str) -> Optional[str]:
        path = self._path(prompt, model)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))['response']
        except (OSError, ValueError, KeyError):
            return None

    def put(self, prompt: str, model: str, response: str) -> None:
        payload = {'model': model, 'prompt': prompt, 'response': response}
        try:
            self._path(prompt, model).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
        except OSError:
            pass  # a cache miss is recoverable; a crash here is not


# ═══════════════════════════════════════════════════════════
# Automatic proxies
# ═══════════════════════════════════════════════════════════

_FINDING_MARKERS = re.compile(
    r'(?i)\b(bug|error|issue|problem|vulnerab\w+|leak|race|overflow|'
    r'injection|deprecat\w+|inefficien\w+|missing|incorrect|unsafe)\b'
)
_LINE_CITATION = re.compile(r'(?i)\blines?\s*#?\s*(\d+)')


def _finding_terms(text: str) -> set:
    """Distinct issue-type keywords a response raises."""
    return {m.lower() for m in _FINDING_MARKERS.findall(text)}


def score_pair(
    pair: ResponsePair,
    line_map: Optional[Dict[int, int]] = None,
) -> UtilityScores:
    """
    Compute automatic proxies for one raw/abstracted response pair.

    Args:
        pair: The two responses.
        line_map: Abstract→original index, so that citations are compared
            in the same numbering rather than being counted as disagreeing
            purely because the abstract file is shorter.

    Returns:
        :class:`UtilityScores`.
    """
    raw_terms = _finding_terms(pair.raw_response)
    abstract_terms = _finding_terms(pair.abstract_response)
    overlap = (
        len(raw_terms & abstract_terms) / len(raw_terms)
        if raw_terms else (1.0 if not abstract_terms else 0.0)
    )

    raw_lines = {int(n) for n in _LINE_CITATION.findall(pair.raw_response)}
    abstract_lines = {int(n) for n in _LINE_CITATION.findall(pair.abstract_response)}
    if line_map:
        index = {int(k): int(v) for k, v in line_map.items()}
        abstract_lines = {index.get(n, n) for n in abstract_lines}

    if raw_lines:
        agreement = len(raw_lines & abstract_lines) / len(raw_lines)
    else:
        agreement = 1.0 if not abstract_lines else 0.0

    raw_length = max(len(pair.raw_response), 1)
    return UtilityScores(
        file_name=pair.file_name,
        task=pair.task,
        issue_overlap=round(overlap, 4),
        line_citation_agreement=round(agreement, 4),
        length_ratio=round(len(pair.abstract_response) / raw_length, 4),
        abstract_is_empty=not pair.abstract_response.strip(),
    )


# ═══════════════════════════════════════════════════════════
# Collection
# ═══════════════════════════════════════════════════════════

def collect_pairs(
    files: Sequence[Dict],
    client,
    task: str = "review",
    privacy_level: str = "high",
    cache: Optional[ResponseCache] = None,
    model: str = "unknown",
) -> List[ResponsePair]:
    """
    Ask the same question of each file raw and abstracted.

    Args:
        files: Corpus entries with ``name`` and ``code``.
        client: An object exposing ``send(code, task) -> response`` with
            ``.content`` and ``.success``.
        task: One of :data:`DEFAULT_QUESTIONS`.
        privacy_level: Level to abstract at.
        cache: Optional response cache.
        model: Model identifier, part of the cache key.

    Returns:
        One :class:`ResponsePair` per file.

    Raises:
        ValueError: If no client is supplied. A utility measurement with no
            model behind it would report fabricated numbers.
    """
    if client is None:
        raise ValueError(
            "collect_pairs requires an LLM client. Utility cannot be "
            "measured without asking a model; see docs/UPGRADE_PLAN.md "
            "Phase 3 for what is gated on this."
        )

    from algorithms.abstract import abstract

    pairs: List[ResponsePair] = []

    for entry in files:
        abstraction = abstract(entry['code'], privacy_level=privacy_level)

        responses = {}
        cached_flags = {}
        for variant, code in (
            ('raw', entry['code']),
            ('abstract', abstraction.abstract_code),
        ):
            prompt = f"{DEFAULT_QUESTIONS.get(task, task)}\n\n{code}"
            hit = cache.get(prompt, model) if cache else None
            if hit is not None:
                responses[variant] = hit
                cached_flags[variant] = True
                continue

            reply = client.send(code, task)
            text = getattr(reply, 'content', '') if getattr(reply, 'success', True) else ''
            responses[variant] = text
            cached_flags[variant] = False
            if cache:
                cache.put(prompt, model, text)

        pairs.append(ResponsePair(
            file_name=entry['name'],
            task=task,
            raw_response=responses['raw'],
            abstract_response=responses['abstract'],
            raw_cached=cached_flags['raw'],
            abstract_cached=cached_flags['abstract'],
        ))

    return pairs


def score_pairs(
    pairs: Sequence[ResponsePair],
    privacy_level: str = "high",
) -> UtilityReport:
    """Aggregate proxies across collected pairs."""
    if not pairs:
        raise ValueError("no response pairs to score")

    scores = [score_pair(pair) for pair in pairs]
    n = len(scores)

    return UtilityReport(
        privacy_level=privacy_level,
        n_pairs=n,
        mean_issue_overlap=round(sum(s.issue_overlap for s in scores) / n, 4),
        mean_line_agreement=round(
            sum(s.line_citation_agreement for s in scores) / n, 4
        ),
        mean_length_ratio=round(sum(s.length_ratio for s in scores) / n, 4),
        mean_composite=round(sum(s.composite for s in scores) / n, 4),
        per_file=scores,
        cache_hits=sum(1 for p in pairs if p.raw_cached and p.abstract_cached),
        api_calls=sum(
            (0 if p.raw_cached else 1) + (0 if p.abstract_cached else 1)
            for p in pairs
        ),
    )


def export_rating_sheet(
    pairs: Sequence[ResponsePair],
    output_dir: Path,
    seed: int = 20260818,
) -> Dict[str, Path]:
    """
    Write a blind rating sheet and a separate answer key.

    Raters see shuffled, unlabelled responses; the mapping from item id to
    raw-or-abstracted lives in a key file they do not open. Keeping the two
    apart is what makes the rating blind — without it, a rater who knows
    which response came from abstracted code cannot un-know it.

    Args:
        pairs: Collected response pairs.
        output_dir: Directory for the sheet and key.
        seed: Shuffle seed, fixed for reproducibility.

    Returns:
        ``{'sheet': Path, 'key': Path}``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    items = []
    key = []
    for pair in pairs:
        for variant, text in (
            ('raw', pair.raw_response),
            ('abstract', pair.abstract_response),
        ):
            item_id = hashlib.sha256(
                f"{pair.file_name}\x00{pair.task}\x00{variant}".encode()
            ).hexdigest()[:12]
            items.append({
                'item_id': item_id,
                'task': pair.task,
                'response': text,
                'rating_correctness': None,   # 1-5, filled by the rater
                'rating_actionability': None,
            })
            key.append({
                'item_id': item_id,
                'file_name': pair.file_name,
                'variant': variant,
            })

    random.Random(seed).shuffle(items)

    sheet_path = output_dir / "rating_sheet.json"
    key_path = output_dir / "rating_key.json"
    sheet_path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    key_path.write_text(
        json.dumps(key, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    return {'sheet': sheet_path, 'key': key_path}
