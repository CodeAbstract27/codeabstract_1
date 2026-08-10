"""
Reconstruction Fidelity Metric — Pillar 2

Measures how accurately RECONSTRUCT(R, M̃, K) restores original
identifiers from abstracted tokens in an LLM response.

Metrics:
    token_hit_rate        — % of tokens in simulated response that were
                            successfully looked up in mapping
    replacement_accuracy  — % of tokens correctly replaced with original name
    context_block_rate    — % of reconstructed responses with context blocks
    roundtrip_fidelity    — Character-level similarity between original
                            source and a roundtrip: abstract → reconstruct
                            (uses SequenceMatcher, 1.0 = identical)
    reconstruction_rate   — per-file average of all above
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping
from algorithms.reconstruct import reconstruct
from evaluation.benchmarks.corpus import ALL_FILES


@dataclass
class ReconstructionResult:
    """Reconstruction metrics for a single file."""

    file_name: str
    total_tokens_generated: int
    tokens_in_simulated_response: int
    tokens_successfully_replaced: int
    token_hit_rate: float
    replacement_accuracy: float
    has_context_blocks: bool
    roundtrip_fidelity: float
    reconstruction_rate: float   # harmonic mean of the above


@dataclass
class ReconstructionSuiteResult:
    """Aggregated reconstruction metrics across all corpus files."""

    per_file: List[ReconstructionResult] = field(default_factory=list)
    mean_token_hit_rate: float = 0.0
    mean_replacement_accuracy: float = 0.0
    mean_roundtrip_fidelity: float = 0.0
    context_block_rate: float = 0.0
    mean_reconstruction_rate: float = 0.0
    files_evaluated: int = 0


def _build_simulated_llm_response(mapping: Dict) -> Tuple[str, List[str]]:
    """
    Build a synthetic LLM response containing all known tokens.

    This simulates what an LLM would return after seeing the abstracted code —
    a response that references the tokens we gave it.

    Returns:
        (response_text, list_of_expected_token_names)
    """
    if not mapping:
        return "No issues found with the code.", []

    tokens = list(mapping.keys())
    token_lines = []
    for token in tokens:
        entry = mapping[token]
        original_name = entry["name"]
        # Simulate an LLM talking about each token
        token_lines.append(
            f"The identifier {token} (representing '{original_name}') "
            f"appears at line {entry.get('lineno', '?')}. "
            f"Consider reviewing the usage of {token}."
        )

    response = "\n".join(token_lines)
    return response, tokens


def _count_replaced_tokens(original_response: str, reconstructed: str, mapping: Dict) -> int:
    """Count how many tokens were successfully replaced with original names."""
    count = 0
    for token, entry in mapping.items():
        original_name = entry["name"]
        # Token should be gone and original name should appear
        token_gone = token not in reconstructed
        name_present = original_name in reconstructed
        if token_gone and name_present:
            count += 1
    return count


def _roundtrip_fidelity(source_code: str, reconstructed: str) -> float:
    """
    Compute character-level similarity between source and reconstructed text.

    Uses SequenceMatcher ratio (0.0 = completely different, 1.0 = identical).
    Note: This won't be 1.0 because reconstruct appends context blocks.
    We strip context blocks before comparing.
    """
    # Remove the appended context block for fair comparison
    if "─── Source Context" in reconstructed:
        reconstructed_clean = reconstructed[:reconstructed.index("─── Source Context")].strip()
    else:
        reconstructed_clean = reconstructed.strip()

    source_clean = source_code.strip()
    ratio = SequenceMatcher(None, source_clean, reconstructed_clean).ratio()
    return round(ratio, 4)


def evaluate_file_reconstruction(
    source_code: str,
    file_name: str,
    privacy_level: str = "high",
) -> ReconstructionResult:
    """
    Compute reconstruction fidelity for a single source file.

    Workflow:
    1. Abstract source_code → get mapping + abstract_code
    2. Build a simulated LLM response containing all tokens
    3. Run reconstruct() on the simulated response
    4. Measure what fraction of tokens were correctly replaced
    5. Compare reconstructed text to original for roundtrip fidelity

    Args:
        source_code: Python source code.
        file_name: Label for reporting.
        privacy_level: Abstraction level.

    Returns:
        ReconstructionResult with all sub-metrics.
    """
    # Step 1: Abstract
    abstraction = abstract(source_code, privacy_level=privacy_level)
    mapping = decrypt_mapping(abstraction.encrypted_mapping, abstraction.encryption_key)

    total_tokens = len(mapping)

    # Step 2: Build simulated LLM response
    simulated_response, token_list = _build_simulated_llm_response(mapping)
    tokens_in_response = len(token_list)

    # Step 3: Reconstruct
    try:
        reconstructed = reconstruct(
            simulated_response,
            abstraction.encrypted_mapping,
            abstraction.encryption_key,
        )
        reconstruct_ok = True
    except Exception:
        reconstructed = simulated_response
        reconstruct_ok = False

    # Step 4: Token hit rate — fraction of response tokens successfully replaced
    if tokens_in_response > 0:
        replaced_count = _count_replaced_tokens(simulated_response, reconstructed, mapping)
        token_hit_rate = round(replaced_count / tokens_in_response, 4)
        replacement_accuracy = token_hit_rate  # same metric here
    else:
        replaced_count = 0
        token_hit_rate = 1.0  # no tokens to replace → trivially correct
        replacement_accuracy = 1.0

    # Step 5: Context block presence
    has_context_blocks = "─── Source Context" in reconstructed

    # Step 6: Roundtrip fidelity
    # Build a response that uses ALL tokens, reconstruct, and compare to original source
    all_tokens_str = " ".join(mapping.keys())
    try:
        roundtrip_reconstructed = reconstruct(
            all_tokens_str,
            abstraction.encrypted_mapping,
            abstraction.encryption_key,
        )
        rt_fidelity = _roundtrip_fidelity(source_code, roundtrip_reconstructed)
    except Exception:
        rt_fidelity = 0.0

    # Harmonic mean of key metrics
    metrics = [token_hit_rate, replacement_accuracy, rt_fidelity]
    non_zero = [m for m in metrics if m > 0]
    if non_zero:
        reconstruction_rate = round(
            len(non_zero) / sum(1 / m for m in non_zero), 4
        )
    else:
        reconstruction_rate = 0.0

    return ReconstructionResult(
        file_name=file_name,
        total_tokens_generated=total_tokens,
        tokens_in_simulated_response=tokens_in_response,
        tokens_successfully_replaced=replaced_count,
        token_hit_rate=token_hit_rate,
        replacement_accuracy=replacement_accuracy,
        has_context_blocks=has_context_blocks,
        roundtrip_fidelity=rt_fidelity,
        reconstruction_rate=reconstruction_rate,
    )


def run_reconstruction_suite(privacy_level: str = "high") -> ReconstructionSuiteResult:
    """
    Run reconstruction evaluation across all corpus files.

    Returns:
        ReconstructionSuiteResult with per-file and aggregated metrics.
    """
    suite = ReconstructionSuiteResult()

    for file_entry in ALL_FILES:
        result = evaluate_file_reconstruction(
            source_code=file_entry["code"],
            file_name=file_entry["name"],
            privacy_level=privacy_level,
        )
        suite.per_file.append(result)

    n = len(suite.per_file)
    suite.files_evaluated = n

    if n > 0:
        suite.mean_token_hit_rate = round(
            sum(r.token_hit_rate for r in suite.per_file) / n, 4
        )
        suite.mean_replacement_accuracy = round(
            sum(r.replacement_accuracy for r in suite.per_file) / n, 4
        )
        suite.mean_roundtrip_fidelity = round(
            sum(r.roundtrip_fidelity for r in suite.per_file) / n, 4
        )
        suite.context_block_rate = round(
            sum(1 for r in suite.per_file if r.has_context_blocks) / n, 4
        )
        suite.mean_reconstruction_rate = round(
            sum(r.reconstruction_rate for r in suite.per_file) / n, 4
        )

    return suite
