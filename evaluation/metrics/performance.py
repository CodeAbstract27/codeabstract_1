"""
Performance Benchmark — Pillar 5

Measures the speed and scalability of CodeAbstract's core operations.

Metrics:
    abstraction_time_ms    — Wall clock time for ABSTRACT(S, k) per file
    reconstruction_time_ms — Wall clock time for RECONSTRUCT per response
    encryption_time_ms     — Time for ENCRYPT + DECRYPT round-trip
    throughput_loc_per_sec — Lines of code processed per second
    scaling_data           — Time vs. file size (small → medium → large)
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping, encrypt_mapping
from algorithms.reconstruct import reconstruct
from evaluation.benchmarks.corpus import ALL_FILES


@dataclass
class PerformanceResult:
    """Performance metrics for a single file."""

    file_name: str
    loc: int
    abstraction_time_ms: float
    reconstruction_time_ms: float
    encryption_time_ms: float
    total_pipeline_time_ms: float
    throughput_loc_per_sec: float
    tokens_generated: int


@dataclass
class ScalingPoint:
    """A single point on the scaling curve."""
    loc: int
    abstraction_time_ms: float
    throughput_loc_per_sec: float


@dataclass
class PerformanceSuiteResult:
    """Aggregated performance metrics across all corpus files."""

    per_file: List[PerformanceResult] = field(default_factory=list)
    mean_abstraction_time_ms: float = 0.0
    mean_reconstruction_time_ms: float = 0.0
    mean_encryption_time_ms: float = 0.0
    mean_pipeline_time_ms: float = 0.0
    mean_throughput_loc_per_sec: float = 0.0
    peak_throughput_loc_per_sec: float = 0.0
    min_throughput_loc_per_sec: float = 0.0
    scaling_curve: List[ScalingPoint] = field(default_factory=list)
    files_evaluated: int = 0


def _measure_ms(func, *args, **kwargs) -> Tuple[float, object]:
    """
    Measure the wall-clock time of a function call in milliseconds.

    Returns:
        (elapsed_ms, return_value)
    """
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = (time.perf_counter() - start) * 1000
    return round(elapsed, 3), result


def _count_loc(source_code: str) -> int:
    """Count non-empty, non-comment lines of code."""
    lines = source_code.strip().splitlines()
    return sum(
        1 for line in lines
        if line.strip() and not line.strip().startswith("#")
    )


def _build_reconstruction_response(mapping: Dict) -> str:
    """Build a short test response with all tokens for reconstruction timing."""
    return " ".join(mapping.keys())


def evaluate_file_performance(
    source_code: str,
    file_name: str,
    loc: int,
    privacy_level: str = "high",
    repetitions: int = 5,
) -> PerformanceResult:
    """
    Benchmark performance for a single source file.

    Uses multiple repetitions and takes the median to reduce noise.

    Args:
        source_code: Python source code.
        file_name: Label for reporting.
        loc: Reported lines of code.
        privacy_level: Abstraction level.
        repetitions: Number of timing runs for stability.

    Returns:
        PerformanceResult with all timing metrics.
    """
    actual_loc = _count_loc(source_code) or loc

    # ── Abstraction timing (median of N runs) ──
    abstraction_times = []
    last_abstraction = None
    for _ in range(repetitions):
        ms, result = _measure_ms(abstract, source_code, privacy_level=privacy_level)
        abstraction_times.append(ms)
        last_abstraction = result
    abstraction_times.sort()
    abstraction_ms = abstraction_times[len(abstraction_times) // 2]

    # ── Encryption round-trip timing ──
    mapping_dict = decrypt_mapping(
        last_abstraction.encrypted_mapping, last_abstraction.encryption_key
    )
    encrypt_times = []
    for _ in range(repetitions):
        start = time.perf_counter()
        enc, key = encrypt_mapping(mapping_dict)
        decrypt_mapping(enc, key)
        elapsed = (time.perf_counter() - start) * 1000
        encrypt_times.append(elapsed)
    encrypt_times.sort()
    encryption_ms = round(encrypt_times[len(encrypt_times) // 2], 3)

    # ── Reconstruction timing ──
    test_response = _build_reconstruction_response(mapping_dict)
    reconstruct_times = []
    for _ in range(repetitions):
        ms, _ = _measure_ms(
            reconstruct,
            test_response,
            last_abstraction.encrypted_mapping,
            last_abstraction.encryption_key,
        )
        reconstruct_times.append(ms)
    reconstruct_times.sort()
    reconstruction_ms = reconstruct_times[len(reconstruct_times) // 2]

    # ── Derived metrics ──
    total_ms = round(abstraction_ms + reconstruction_ms + encryption_ms, 3)
    throughput = round(actual_loc / (abstraction_ms / 1000), 1) if abstraction_ms > 0 else 0.0

    return PerformanceResult(
        file_name=file_name,
        loc=actual_loc,
        abstraction_time_ms=abstraction_ms,
        reconstruction_time_ms=reconstruction_ms,
        encryption_time_ms=encryption_ms,
        total_pipeline_time_ms=total_ms,
        throughput_loc_per_sec=throughput,
        tokens_generated=len(mapping_dict),
    )


def _build_scaling_corpus() -> List[Tuple[int, str]]:
    """
    Build progressively larger code snippets for the scaling experiment.

    Returns list of (loc, code) tuples from ~30 to ~500 LOC.
    """
    base = ALL_FILES[1]["code"]  # e-commerce file as seed

    scaling_samples = []
    for multiplier in [1, 2, 3, 5, 8]:
        code = (base * multiplier)
        loc = _count_loc(code)
        scaling_samples.append((loc, code))

    return scaling_samples


def run_performance_suite(privacy_level: str = "high") -> PerformanceSuiteResult:
    """
    Run performance benchmarks across all corpus files and generate scaling data.

    Returns:
        PerformanceSuiteResult with per-file and aggregated metrics.
    """
    suite = PerformanceSuiteResult()

    for file_entry in ALL_FILES:
        result = evaluate_file_performance(
            source_code=file_entry["code"],
            file_name=file_entry["name"],
            loc=file_entry["loc"],
            privacy_level=privacy_level,
        )
        suite.per_file.append(result)

    n = len(suite.per_file)
    suite.files_evaluated = n

    if n > 0:
        suite.mean_abstraction_time_ms = round(
            sum(r.abstraction_time_ms for r in suite.per_file) / n, 3
        )
        suite.mean_reconstruction_time_ms = round(
            sum(r.reconstruction_time_ms for r in suite.per_file) / n, 3
        )
        suite.mean_encryption_time_ms = round(
            sum(r.encryption_time_ms for r in suite.per_file) / n, 3
        )
        suite.mean_pipeline_time_ms = round(
            sum(r.total_pipeline_time_ms for r in suite.per_file) / n, 3
        )

        throughputs = [r.throughput_loc_per_sec for r in suite.per_file]
        suite.mean_throughput_loc_per_sec = round(sum(throughputs) / n, 1)
        suite.peak_throughput_loc_per_sec = max(throughputs)
        suite.min_throughput_loc_per_sec = min(throughputs)

    # ── Scaling curve ──
    scaling_samples = _build_scaling_corpus()
    for loc, code in scaling_samples:
        ms, _ = _measure_ms(abstract, code, privacy_level=privacy_level)
        throughput = round(loc / (ms / 1000), 1) if ms > 0 else 0.0
        suite.scaling_curve.append(ScalingPoint(
            loc=loc,
            abstraction_time_ms=round(ms, 3),
            throughput_loc_per_sec=throughput,
        ))

    return suite
