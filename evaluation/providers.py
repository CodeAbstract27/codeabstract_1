"""
Cross-Provider Comparison

Phase 4 — the evaluation half of the provider workstream, and the exit
criterion "the same file reviewed through all three providers, with results
compared in the evaluation".

The comparison is deliberately *paired*: one file is abstracted once, and
the identical payload goes to every provider. Abstracting per provider
would let token numbering differ between runs and make any disagreement
unattributable — the whole point is that the only variable is the model.

What is measured, and why each is here rather than a generic benchmark:

* **Token fidelity** — the fraction of abstraction tokens in a response
  that exist in the mapping. This is the project's own question, not a
  general one: the system instruction asks the model to reason in
  ``FUNC_0``/``VAR_1``, and a provider that invents ``FUNC_9`` or quietly
  renames things back to plausible English produces answers that cannot be
  reconstructed. It is the closest thing here to a per-provider utility
  measure that does not need human raters.
* **Line-citation resolvability** — how many cited lines exist in the
  abstract file at all. A model citing line 400 of a 50-line file is not
  answering about this file.
* **Agreement** — pairwise overlap of the issue terms each provider
  raises, and of the lines they point at. High agreement means the choice
  of provider does not change the advice; low agreement means the headline
  number from any single provider is not a property of the system.
* **Cost and latency** — tokens and seconds, per provider.

What this module does **not** do is score answer quality. Deciding whether
an answer is correct is the blind-rating job that :mod:`evaluation.utility`
prepares and Phase 3 records as blocked on human raters. Reporting a
"winner" from term overlap would be exactly the kind of metric-that-cannot-
fail the audit was written about.

Calling this without clients raises rather than returning zeros, for the
same reason ``collect_pairs`` does.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from evaluation.utility import ResponseCache, _FINDING_MARKERS, _LINE_CITATION

# Any token the abstraction engine can emit, in either language.
_TOKEN = re.compile(r'\b((?:FUNC|VAR|SECRET|CONST|NUM|CLASS|MODULE)_\d+)\b')


@dataclass
class ProviderResult:
    """One provider's answer to one file."""

    provider: str
    model: str
    file_name: str
    success: bool
    response: str = ""
    error: Optional[str] = None
    response_time: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_reported: bool = False
    cached: bool = False

    # -- derived signals ------------------------------------------------

    def tokens_used(self) -> set:
        """Abstraction tokens the response referred to."""
        return set(_TOKEN.findall(self.response))

    def finding_terms(self) -> set:
        """Issue-type keywords the response raised."""
        return {m.lower() for m in _FINDING_MARKERS.findall(self.response)}

    def cited_lines(self) -> set:
        """Line numbers the response cited."""
        return {int(n) for n in _LINE_CITATION.findall(self.response)}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'provider': self.provider,
            'model': self.model,
            'file_name': self.file_name,
            'success': self.success,
            'error': self.error,
            'response_time': round(self.response_time, 4),
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'tokens_reported': self.tokens_reported,
            'cached': self.cached,
            'response_chars': len(self.response),
        }


@dataclass
class ProviderScores:
    """Aggregated behaviour of one provider across the corpus."""

    provider: str
    model: str
    files: int
    successes: int
    token_fidelity: float
    line_resolvability: float
    mean_response_time: float
    mean_response_chars: float
    total_prompt_tokens: int
    total_completion_tokens: int
    tokens_reported: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'provider': self.provider,
            'model': self.model,
            'files': self.files,
            'successes': self.successes,
            'token_fidelity': self.token_fidelity,
            'line_resolvability': self.line_resolvability,
            'mean_response_time': self.mean_response_time,
            'mean_response_chars': self.mean_response_chars,
            'total_prompt_tokens': self.total_prompt_tokens,
            'total_completion_tokens': self.total_completion_tokens,
            'tokens_reported': self.tokens_reported,
        }


@dataclass
class ProviderComparison:
    """The whole comparison: per-provider scores plus pairwise agreement."""

    task: str
    privacy_level: str
    files: List[str] = field(default_factory=list)
    per_provider: List[ProviderScores] = field(default_factory=list)
    results: List[ProviderResult] = field(default_factory=list)
    finding_agreement: Dict[str, float] = field(default_factory=dict)
    line_agreement: Dict[str, float] = field(default_factory=dict)

    def caveat(self) -> str:
        return (
            "Token fidelity and agreement describe behaviour, not answer "
            "quality. Judging correctness needs the blind rating sheet in "
            "evaluation.utility; see docs/UPGRADE_PLAN.md Phase 3."
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'task': self.task,
            'privacy_level': self.privacy_level,
            'files': self.files,
            'providers': [scores.to_dict() for scores in self.per_provider],
            'finding_agreement': self.finding_agreement,
            'line_agreement': self.line_agreement,
            'results': [result.to_dict() for result in self.results],
            'caveat': self.caveat(),
        }


def _jaccard(left: set, right: set) -> float:
    """Overlap of two sets; 1.0 when both are empty (they agree on nothing found)."""
    if not left and not right:
        return 1.0
    union = left | right
    return round(len(left & right) / len(union), 4) if union else 1.0


def collect_responses(
    files: Sequence[Dict],
    clients: Sequence,
    task: str = "review",
    privacy_level: str = "high",
    query: Optional[str] = None,
    cache: Optional[ResponseCache] = None,
) -> List[ProviderResult]:
    """
    Send the same abstracted payload to every provider.

    Args:
        files: Corpus entries with ``name`` and ``code`` (and optionally
            ``language``, defaulting to Python).
        clients: Clients satisfying :class:`llm.base.LLMClient`.
        task: Preset task name.
        privacy_level: Level to abstract at.
        query: Optional free-form question, abstracted with the same
            mapping as the code.
        cache: Optional response cache, so a comparison is reproducible
            without keys.

    Returns:
        One :class:`ProviderResult` per (file, provider).

    Raises:
        ValueError: If no clients are supplied.
    """
    if not clients:
        raise ValueError(
            "compare_providers requires at least one LLM client. A "
            "cross-provider comparison with no providers would be a table "
            "of zeros; see docs/UPGRADE_PLAN.md Phase 4."
        )

    from algorithms.abstract_source import abstract_source
    from algorithms.encrypt import decrypt_mapping
    from core.query_abstractor import abstract_query
    from llm.base import build_prompt

    results: List[ProviderResult] = []

    for entry in files:
        language = entry.get('language', 'python')
        abstraction = abstract_source(
            entry['code'], language=language, privacy_level=privacy_level,
        )

        query_text = None
        if query:
            mapping = decrypt_mapping(
                abstraction.encrypted_mapping, abstraction.encryption_key
            )
            query_text = abstract_query(query, mapping).text

        prompt = build_prompt(
            abstraction.abstract_code, task=task, query=query_text, language=language,
        )

        for client in clients:
            hit = cache.get(prompt, client.model) if cache else None
            if hit is not None:
                results.append(ProviderResult(
                    provider=client.provider,
                    model=client.model,
                    file_name=entry['name'],
                    success=True,
                    response=hit,
                    cached=True,
                ))
                continue

            reply = client.send(
                abstract_code=abstraction.abstract_code,
                task=task,
                query=query_text,
                language=language,
            )
            usage = getattr(reply, 'usage', None)
            results.append(ProviderResult(
                provider=client.provider,
                model=client.model,
                file_name=entry['name'],
                success=bool(reply.success),
                response=reply.content or "",
                error=reply.error,
                response_time=reply.response_time,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                tokens_reported=bool(usage and usage.reported),
            ))
            if cache and reply.success:
                cache.put(prompt, client.model, reply.content or "")

    return results


def score_comparison(
    results: Sequence[ProviderResult],
    known_tokens: Optional[Dict[str, set]] = None,
    line_counts: Optional[Dict[str, int]] = None,
    task: str = "review",
    privacy_level: str = "high",
) -> ProviderComparison:
    """
    Aggregate collected responses into per-provider scores and agreement.

    Args:
        results: Output of :func:`collect_responses`.
        known_tokens: ``file_name -> set of tokens in that file's mapping``.
            Token fidelity is only computable with it; without it the
            metric is reported as 1.0 and flagged by ``tokens_reported``
            being the only usage signal, so callers should pass it.
        line_counts: ``file_name -> number of lines in the abstract file``.
        task: Task the responses answered.
        privacy_level: Level used.

    Returns:
        A :class:`ProviderComparison`.
    """
    known_tokens = known_tokens or {}
    line_counts = line_counts or {}

    by_provider: Dict[str, List[ProviderResult]] = {}
    for result in results:
        by_provider.setdefault(result.provider, []).append(result)

    per_provider: List[ProviderScores] = []
    for provider, provider_results in sorted(by_provider.items()):
        successes = [r for r in provider_results if r.success]

        fidelity_scores = []
        resolvable_scores = []
        for result in successes:
            used = result.tokens_used()
            valid = known_tokens.get(result.file_name)
            if used and valid is not None:
                fidelity_scores.append(len(used & valid) / len(used))

            cited = result.cited_lines()
            total_lines = line_counts.get(result.file_name)
            if cited and total_lines:
                resolvable_scores.append(
                    len([n for n in cited if 1 <= n <= total_lines]) / len(cited)
                )

        per_provider.append(ProviderScores(
            provider=provider,
            model=provider_results[0].model,
            files=len(provider_results),
            successes=len(successes),
            token_fidelity=round(
                sum(fidelity_scores) / len(fidelity_scores), 4
            ) if fidelity_scores else 0.0,
            line_resolvability=round(
                sum(resolvable_scores) / len(resolvable_scores), 4
            ) if resolvable_scores else 0.0,
            mean_response_time=round(
                sum(r.response_time for r in successes) / len(successes), 4
            ) if successes else 0.0,
            mean_response_chars=round(
                sum(len(r.response) for r in successes) / len(successes), 1
            ) if successes else 0.0,
            total_prompt_tokens=sum(r.prompt_tokens for r in provider_results),
            total_completion_tokens=sum(r.completion_tokens for r in provider_results),
            tokens_reported=any(r.tokens_reported for r in provider_results),
        ))

    # ── Pairwise agreement, averaged over files ──────
    finding_agreement: Dict[str, float] = {}
    line_agreement: Dict[str, float] = {}
    providers = sorted(by_provider)

    for index, left in enumerate(providers):
        for right in providers[index + 1:]:
            pair = f"{left}|{right}"
            findings, lines = [], []

            for file_name in {r.file_name for r in results}:
                left_result = next(
                    (r for r in by_provider[left]
                     if r.file_name == file_name and r.success), None
                )
                right_result = next(
                    (r for r in by_provider[right]
                     if r.file_name == file_name and r.success), None
                )
                if left_result is None or right_result is None:
                    continue
                findings.append(_jaccard(
                    left_result.finding_terms(), right_result.finding_terms()
                ))
                lines.append(_jaccard(
                    left_result.cited_lines(), right_result.cited_lines()
                ))

            if findings:
                finding_agreement[pair] = round(sum(findings) / len(findings), 4)
                line_agreement[pair] = round(sum(lines) / len(lines), 4)

    return ProviderComparison(
        task=task,
        privacy_level=privacy_level,
        files=sorted({r.file_name for r in results}),
        per_provider=per_provider,
        results=list(results),
        finding_agreement=finding_agreement,
        line_agreement=line_agreement,
    )


def compare_providers(
    files: Sequence[Dict],
    clients: Sequence,
    task: str = "review",
    privacy_level: str = "high",
    query: Optional[str] = None,
    cache: Optional[ResponseCache] = None,
) -> ProviderComparison:
    """
    Run the full comparison: collect, then score.

    Abstracts each file a second time to recover the token set and line
    count the scoring needs. That is cheap (abstraction is local and
    deterministic) and keeps :func:`collect_responses` returning plain
    transport results rather than a bundle of scoring state.
    """
    from algorithms.abstract_source import abstract_source
    from algorithms.encrypt import decrypt_mapping

    results = collect_responses(
        files=files, clients=clients, task=task,
        privacy_level=privacy_level, query=query, cache=cache,
    )

    known_tokens: Dict[str, set] = {}
    line_counts: Dict[str, int] = {}
    for entry in files:
        abstraction = abstract_source(
            entry['code'],
            language=entry.get('language', 'python'),
            privacy_level=privacy_level,
        )
        mapping = decrypt_mapping(
            abstraction.encrypted_mapping, abstraction.encryption_key
        )
        known_tokens[entry['name']] = set(mapping)
        line_counts[entry['name']] = len(abstraction.abstract_code.splitlines())

    return score_comparison(
        results,
        known_tokens=known_tokens,
        line_counts=line_counts,
        task=task,
        privacy_level=privacy_level,
    )
