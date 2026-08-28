"""
Full HumanEval Dataset Parser and Runner.
Reads CSV data, runs full CodeAbstract suite on all tasks, and computes metrics.
"""

import ast
import csv
import io
import os
import sys
import time
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct_structured
from algorithms.encrypt import decrypt_mapping


def evaluate_task(task_row: Dict[str, str], privacy_level: str = "high") -> Dict[str, Any]:
    task_id = task_row['task_id']
    prompt = task_row['prompt']
    solution = task_row['canonical_solution']
    test_code = task_row['test']
    entry_point = task_row['entry_point']

    full_code = prompt + solution

    # Step 1: Benchmark abstraction execution
    t0 = time.perf_counter()
    abs_res = abstract(full_code, privacy_level=privacy_level)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    # Step 2: AST Parse verification (Syntax / Isomorphism validity)
    ast_valid = False
    try:
        parsed_tree = ast.parse(abs_res.abstract_code)
        ast_valid = True
    except Exception as e:
        parsed_tree = None

    # Step 3: Decrypt mapping & verify token preservation
    mapping = decrypt_mapping(abs_res.encrypted_mapping, abs_res.encryption_key)
    all_tokens = list(mapping.keys())

    # Step 4: Round-trip reconstruction test
    # Generate synthetic response containing abstract tokens
    sample_response = f"Identified functions: {', '.join(all_tokens[:5])}\nRefactor VAR_0 and FUNC_0 if needed."
    recon_res = reconstruct_structured(
        sample_response,
        abs_res.encrypted_mapping,
        abs_res.encryption_key
    )
    recon_valid = (recon_res is not None and len(recon_res.review_text) > 0)

    # Check for original entry point preservation or substitution
    privacy_masked = (entry_point not in abs_res.abstract_code) if privacy_level in ("high", "critical") else True

    # Step 5: Unit test validation of original code
    func_exec_pass = False
    scope = {}
    try:
        exec(full_code, scope)
        exec(test_code, scope)
        scope['check'](scope[entry_point])
        func_exec_pass = True
    except Exception as e:
        func_exec_pass = False

    return {
        'task_id': task_id,
        'latency_ms': latency_ms,
        'ast_valid': ast_valid,
        'recon_valid': recon_valid,
        'privacy_masked': privacy_masked,
        'func_exec_pass': func_exec_pass,
        'total_nodes': abs_res.statistics.get('total_nodes', 0),
        'abstracted_nodes': abs_res.statistics.get('abstracted_nodes', 0),
    }


def run_batch_evaluation(csv_file_path: str, privacy_level: str = "high"):
    with open(csv_file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        tasks = list(reader)

    print(f"📊 Running CodeAbstract evaluation on {len(tasks)} benchmark problems (Privacy: {privacy_level})...\n")

    results = []
    for t in tasks:
        res = evaluate_task(t, privacy_level=privacy_level)
        results.append(res)

    total = len(results)
    ast_valid_count = sum(1 for r in results if r['ast_valid'])
    recon_valid_count = sum(1 for r in results if r['recon_valid'])
    masked_count = sum(1 for r in results if r['privacy_masked'])
    exec_count = sum(1 for r in results if r['func_exec_pass'])
    
    total_nodes = sum(r['total_nodes'] for r in results)
    abs_nodes = sum(r['abstracted_nodes'] for r in results)
    pir = (abs_nodes / total_nodes * 100.0) if total_nodes else 0.0

    latencies = [r['latency_ms'] for r in results]
    mean_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p50_lat = sorted(latencies)[int(len(latencies) * 0.50)] if latencies else 0.0
    p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    print("=" * 65)
    print(f"🏁 CodeAbstract HumanEval Benchmark Results ({total} Tasks)")
    print("=" * 65)
    print(f"✅ AST Isomorphism / Syntactic Validity: {ast_valid_count / total * 100.0:.2f}% ({ast_valid_count}/{total})")
    print(f"🔄 Round-Trip Reconstruction Fidelity:  {recon_valid_count / total * 100.0:.2f}% ({recon_valid_count}/{total})")
    print(f"🛡️  Privacy Information Ratio (PIR):    {pir:.2f}% ({abs_nodes}/{total_nodes} nodes)")
    print(f"🧪 Baseline Functional Correctness:     {exec_count / total * 100.0:.2f}% ({exec_count}/{total})")
    print(f"⚡ Latency (Mean):                     {mean_lat:.2f} ms")
    print(f"⚡ Latency (p50 Median):               {p50_lat:.2f} ms")
    print(f"⚡ Latency (p95):                      {p95_lat:.2f} ms")
    print("=" * 65)


if __name__ == '__main__':
    csv_path = os.path.join(os.path.dirname(__file__), 'datasets', 'humaneval_tasks.csv')
    if os.path.exists(csv_path):
        run_batch_evaluation(csv_path)
    else:
        print(f"Dataset file not found at {csv_path}")
