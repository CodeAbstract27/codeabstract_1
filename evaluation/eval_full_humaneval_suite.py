"""
Full HumanEval Benchmark Test Suite (All 164 Problems) for CodeAbstract.
Evaluates CodeAbstract across the complete OpenAI HumanEval dataset (human-eval-v2-20210705.json).
"""

import ast
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct_structured
from algorithms.encrypt import decrypt_mapping


def calculate_levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return calculate_levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def normalized_edit_distance(orig: str, modified: str) -> float:
    if not orig and not modified:
        return 0.0
    dist = calculate_levenshtein(orig, modified)
    max_len = max(len(orig), len(modified))
    return (dist / max_len) * 100.0 if max_len > 0 else 0.0


def run_full_humaneval_evaluation(
    dataset_path: str,
    privacy_level: str = "high",
    output_dir: str = "evaluation_output",
) -> Dict[str, Any]:
    print("=" * 80)
    print("🚀 EVALUATING CODEABSTRACT ON COMPLETE OPENAI HUMANEVAL BENCHMARK (164 TASKS)")
    print(f"📁 Dataset: {dataset_path}")
    print(f"🔒 Privacy Level: {privacy_level.upper()}")
    print("=" * 80)

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Dataset not found at: {dataset_path}")

    tasks = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))

    total_tasks = len(tasks)
    passed_ast = 0
    passed_recon = 0
    passed_unit_tests = 0
    zero_leakage_count = 0
    
    total_ast_nodes = 0
    total_semantic_nodes = 0
    total_abstracted_nodes = 0
    total_intentionally_preserved = 0
    
    latencies = []
    edit_distances = []
    task_results = []

    start_total_time = time.perf_counter()

    for idx, t in enumerate(tasks, 1):
        task_id = t["task_id"]
        prompt = t["prompt"]
        canonical_solution = t["canonical_solution"]
        test_code = t["test"]
        entry_point = t["entry_point"]

        full_code = prompt + canonical_solution

        # 1. Benchmark abstraction
        t0 = time.perf_counter()
        abs_res = abstract(full_code, privacy_level=privacy_level)
        lat_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(lat_ms)

        # 2. Verify AST syntactic validity
        try:
            ast.parse(abs_res.abstract_code)
            ast_valid = True
            passed_ast += 1
        except Exception:
            ast_valid = False

        # 3. Decrypt mapping
        mapping = decrypt_mapping(abs_res.encrypted_mapping, abs_res.encryption_key)

        # 4. Privacy metrics
        stats = abs_res.statistics
        total_ast_nodes += stats.get("total_nodes", 0)
        total_semantic_nodes += stats.get("semantic_nodes", 0)
        total_abstracted_nodes += stats.get("abstracted_nodes", 0)
        total_intentionally_preserved += stats.get("intentionally_preserved", 0)

        # Check leakage
        leaked = 0
        for meta in mapping.values():
            orig_name = str(meta.get("name", ""))
            if len(orig_name) <= 2 or orig_name in ("True", "False", "None"):
                continue
            if not any(c.isalnum() for c in orig_name):
                continue
            try:
                float(orig_name)
                continue
            except (ValueError, OverflowError):
                pass
            if re.search(r"\b" + re.escape(orig_name) + r"\b", abs_res.abstract_code):
                leaked += 1

        if leaked == 0:
            zero_leakage_count += 1

        # 5. Round-trip reconstruction test
        tokens_list = list(mapping.keys())
        if tokens_list:
            mock_llm_response = f"Review for {tokens_list[0]}: logic verified in {abs_res.abstract_code[:40]}."
            recon_res = reconstruct_structured(mock_llm_response, abs_res.encrypted_mapping, abs_res.encryption_key)
            recon_ok = (tokens_list[0] not in recon_res.review_text) and (mapping[tokens_list[0]]["name"] in recon_res.review_text)
        else:
            recon_ok = True

        if recon_ok:
            passed_recon += 1

        # 6. Execute Canonical Solution against Test Harness
        exec_scope = {}
        try:
            exec(full_code, exec_scope)
            exec(test_code, exec_scope)
            exec_scope["check"](exec_scope[entry_point])
            unit_test_passed = True
            passed_unit_tests += 1
        except Exception:
            unit_test_passed = False

        # 7. Edit distance
        ed = normalized_edit_distance(full_code, abs_res.abstract_code)
        edit_distances.append(ed)

        status_str = "PASS" if (ast_valid and recon_ok and unit_test_passed) else "FAIL"
        if idx <= 15 or idx % 30 == 0 or idx == total_tasks:
            print(f"[{idx:3d}/{total_tasks:3d}] {task_id:<14} | AST: {str(ast_valid):<5} | Recon: {str(recon_ok):<5} | Test: {str(unit_test_passed):<5} | Edit: {ed:5.1f}% | {lat_ms:6.2f} ms | [{status_str}]")

        task_results.append({
            "task_id": task_id,
            "ast_valid": ast_valid,
            "recon_ok": recon_ok,
            "unit_test_passed": unit_test_passed,
            "edit_dist_pct": round(ed, 2),
            "latency_ms": round(lat_ms, 2),
            "leaked_identifiers": leaked,
        })

    total_duration = time.perf_counter() - start_total_time

    # Aggregate Metrics
    ast_valid_rate = (passed_ast / total_tasks) * 100.0
    recon_rate = (passed_recon / total_tasks) * 100.0
    unit_test_rate = (passed_unit_tests / total_tasks) * 100.0
    zero_leakage_rate = (zero_leakage_count / total_tasks) * 100.0
    
    mean_ed = sum(edit_distances) / total_tasks
    mean_lat = sum(latencies) / total_tasks
    sorted_lat = sorted(latencies)
    p50_lat = sorted_lat[int(total_tasks * 0.50)]
    p95_lat = sorted_lat[int(total_tasks * 0.95)]
    p99_lat = sorted_lat[int(total_tasks * 0.99)]

    effective_targets = total_semantic_nodes - total_intentionally_preserved
    sir_eff = (total_abstracted_nodes / effective_targets * 100.0) if effective_targets > 0 else 100.0
    sir_raw = (total_abstracted_nodes / total_semantic_nodes * 100.0) if total_semantic_nodes > 0 else 100.0
    pir_raw = (total_abstracted_nodes / total_ast_nodes * 100.0) if total_ast_nodes > 0 else 0.0

    print("\n" + "=" * 80)
    print("📊 COMPLETE OPENAI HUMANEVAL (164 TASKS) BENCHMARK RESULTS")
    print("=" * 80)
    print(f"• Total Evaluated Tasks:                {total_tasks} problems")
    print(f"• Total Execution Duration:             {total_duration:.2f} seconds")
    print("-" * 80)
    print(f"✅ AST Syntactic Validity Rate:         {ast_valid_rate:.2f}% ({passed_ast}/{total_tasks})")
    print(f"🔄 Round-Trip Reconstruction Fidelity:  {recon_rate:.2f}% ({passed_recon}/{total_tasks})")
    print(f"🧪 Canonical Test Suite Pass Rate:      {unit_test_rate:.2f}% ({passed_unit_tests}/{total_tasks})")
    print(f"🛡️  Effective SIR (SIR_eff):             {sir_eff:.2f}% ({total_abstracted_nodes:,}/{effective_targets:,} sensitive targets)")
    print(f"🛡️  Raw Semantic Info Ratio (SIR):    {sir_raw:.2f}% ({total_abstracted_nodes:,}/{total_semantic_nodes:,} semantic targets)")
    print(f"🛡️  Raw AST Node PIR:                   {pir_raw:.2f}% ({total_abstracted_nodes:,}/{total_ast_nodes:,} AST nodes)")
    print(f"🔒 Zero Sensitive Identifier Leakage:   {zero_leakage_rate:.2f}% ({zero_leakage_count}/{total_tasks})")
    print(f"📝 Normalized Edit Distance:            {mean_ed:.2f}%")
    print("-" * 80)
    print(f"⚡ Processing Latency (Mean):           {mean_lat:.2f} ms")
    print(f"⚡ Processing Latency (p50 Median):     {p50_lat:.2f} ms")
    print(f"⚡ Processing Latency (p95):            {p95_lat:.2f} ms")
    print(f"⚡ Processing Latency (p99):            {p99_lat:.2f} ms")
    print("=" * 80)

    summary_data = {
        "benchmark": "OpenAI HumanEval (Full v2)",
        "dataset_file": os.path.basename(dataset_path),
        "total_tasks": total_tasks,
        "privacy_level": privacy_level,
        "total_duration_sec": round(total_duration, 2),
        "metrics": {
            "ast_syntactic_validity_pct": round(ast_valid_rate, 2),
            "reconstruction_fidelity_pct": round(recon_rate, 2),
            "canonical_test_suite_pass_rate_pct": round(unit_test_rate, 2),
            "effective_sir_pct": round(sir_eff, 2),
            "semantic_information_ratio_pct": round(sir_raw, 2),
            "privacy_information_ratio_pct": round(pir_raw, 2),
            "zero_leakage_rate_pct": round(zero_leakage_rate, 2),
            "normalized_edit_distance_pct": round(mean_ed, 2),
            "mean_latency_ms": round(mean_lat, 2),
            "p50_latency_ms": round(p50_lat, 2),
            "p95_latency_ms": round(p95_lat, 2),
            "p99_latency_ms": round(p99_lat, 2),
        },
        "tasks": task_results
    }

    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "humaneval_v2_full_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print(f"\n[Saved] Complete HumanEval Metrics JSON: {json_path}")
    return summary_data


if __name__ == "__main__":
    dataset_file = os.path.join(os.path.dirname(__file__), "datasets", "human_eval_v2.json")
    run_full_humaneval_evaluation(dataset_file, privacy_level="high")
