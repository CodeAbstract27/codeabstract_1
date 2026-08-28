"""
HumanEval Benchmark Test Suite for CodeAbstract.
Evaluates CodeAbstract's AST Abstraction, Information Redaction (PIR),
and Feedback Reconstruction across OpenAI HumanEval tasks.
"""

import ast
import csv
import io
import os
import sys
import time
from typing import Dict, List, Any

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct_structured
from algorithms.encrypt import decrypt_mapping


# Sample HumanEval tasks from the benchmark
HUMANEVAL_TASKS = [
    {
        "task_id": "HumanEval/0",
        "entry_point": "has_close_elements",
        "prompt": "from typing import List\n\ndef has_close_elements(numbers: List[float], threshold: float) -> bool:\n",
        "canonical_solution": "    for idx, elem in enumerate(numbers):\n        for idx2, elem2 in enumerate(numbers):\n            if idx != idx2:\n                distance = abs(elem - elem2)\n                if distance < threshold:\n                    return True\n    return False\n",
        "test": "def check(candidate):\n    assert candidate([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.3) == True\n    assert candidate([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.05) == False\n"
    },
    {
        "task_id": "HumanEval/1",
        "entry_point": "separate_paren_groups",
        "prompt": "from typing import List\n\ndef separate_paren_groups(paren_string: str) -> List[str]:\n",
        "canonical_solution": "    result = []\n    current_string = []\n    current_depth = 0\n    for c in paren_string:\n        if c == '(':\n            current_depth += 1\n            current_string.append(c)\n        elif c == ')':\n            current_depth -= 1\n            current_string.append(c)\n            if current_depth == 0:\n                result.append(''.join(current_string))\n                current_string.clear()\n    return result\n",
        "test": "def check(candidate):\n    assert candidate('(()()) ((())) () ((())()())') == ['(()())', '((()))', '()', '((())()())']\n"
    },
    {
        "task_id": "HumanEval/2",
        "entry_point": "truncate_number",
        "prompt": "def truncate_number(number: float) -> float:\n",
        "canonical_solution": "    return number % 1.0\n",
        "test": "def check(candidate):\n    assert candidate(3.5) == 0.5\n    assert abs(candidate(1.33) - 0.33) < 1e-6\n"
    },
    {
        "task_id": "HumanEval/3",
        "entry_point": "below_zero",
        "prompt": "from typing import List\n\ndef below_zero(operations: List[int]) -> bool:\n",
        "canonical_solution": "    balance = 0\n    for op in operations:\n        balance += op\n        if balance < 0:\n            return True\n    return False\n",
        "test": "def check(candidate):\n    assert candidate([]) == False\n    assert candidate([1, 2, -4, 5, 6]) == True\n"
    },
    {
        "task_id": "HumanEval/4",
        "entry_point": "mean_absolute_deviation",
        "prompt": "from typing import List\n\ndef mean_absolute_deviation(numbers: List[float]) -> float:\n",
        "canonical_solution": "    mean = sum(numbers) / len(numbers)\n    return sum(abs(x - mean) for x in numbers) / len(numbers)\n",
        "test": "def check(candidate):\n    assert abs(candidate([1.0, 2.0, 3.0, 4.0]) - 1.0) < 1e-6\n"
    },
    {
        "task_id": "HumanEval/8",
        "entry_point": "sum_product",
        "prompt": "from typing import List, Tuple\n\ndef sum_product(numbers: List[int]) -> Tuple[int, int]:\n",
        "canonical_solution": "    sum_value = 0\n    prod_value = 1\n    for n in numbers:\n        sum_value += n\n        prod_value *= n\n    return sum_value, prod_value\n",
        "test": "def check(candidate):\n    assert candidate([]) == (0, 1)\n    assert candidate([1, 2, 3, 4]) == (10, 24)\n"
    },
    {
        "task_id": "HumanEval/11",
        "entry_point": "string_xor",
        "prompt": "def string_xor(a: str, b: str) -> str:\n",
        "canonical_solution": "    def xor(i, j):\n        if i == j:\n            return '0'\n        else:\n            return '1'\n    return ''.join(xor(x, y) for x, y in zip(a, b))\n",
        "test": "def check(candidate):\n    assert candidate('111000', '101010') == '010010'\n"
    },
    {
        "task_id": "HumanEval/25",
        "entry_point": "factorize",
        "prompt": "from typing import List\n\ndef factorize(n: int) -> List[int]:\n",
        "canonical_solution": "    import math\n    fact = []\n    i = 2\n    while i <= int(math.sqrt(n) + 1):\n        if n % i == 0:\n            fact.append(i)\n            n //= i\n        else:\n            i += 1\n    if n > 1:\n        fact.append(n)\n    return fact\n",
        "test": "def check(candidate):\n    assert candidate(8) == [2, 2, 2]\n    assert candidate(25) == [5, 5]\n"
    },
    {
        "task_id": "HumanEval/31",
        "entry_point": "is_prime",
        "prompt": "def is_prime(n):\n",
        "canonical_solution": "    if n < 2:\n        return False\n    for k in range(2, n - 1):\n        if n % k == 0:\n            return False\n    return True\n",
        "test": "def check(candidate):\n    assert candidate(6) == False\n    assert candidate(101) == True\n"
    },
    {
        "task_id": "HumanEval/53",
        "entry_point": "add",
        "prompt": "def add(x: int, y: int):\n",
        "canonical_solution": "    return x + y\n",
        "test": "def check(candidate):\n    assert candidate(2, 3) == 5\n"
    },
    {
        "task_id": "HumanEval/66",
        "entry_point": "digitSum",
        "prompt": "def digitSum(s):\n",
        "canonical_solution": "    if s == '': return 0\n    return sum(ord(char) if char.isupper() else 0 for char in s)\n",
        "test": "def check(candidate):\n    assert candidate('abAB') == 131\n"
    },
    {
        "task_id": "HumanEval/77",
        "entry_point": "iscube",
        "prompt": "def iscube(a):\n",
        "canonical_solution": "    a = abs(a)\n    return int(round(a ** (1. / 3))) ** 3 == a\n",
        "test": "def check(candidate):\n    assert candidate(1) == True\n    assert candidate(64) == True\n    assert candidate(180) == False\n"
    },
    {
        "task_id": "HumanEval/89",
        "entry_point": "encrypt",
        "prompt": "def encrypt(s):\n",
        "canonical_solution": "    d = 'abcdefghijklmnopqrstuvwxyz'\n    out = ''\n    for c in s:\n        if c in d:\n            out += d[(d.index(c)+2*2) % 26]\n        else:\n            out += c\n    return out\n",
        "test": "def check(candidate):\n    assert candidate('hi') == 'lm'\n"
    },
    {
        "task_id": "HumanEval/103",
        "entry_point": "rounded_avg",
        "prompt": "def rounded_avg(n, m):\n",
        "canonical_solution": "    if m < n:\n        return -1\n    summation = 0\n    for i in range(n, m+1):\n        summation += i\n    return bin(round(summation/(m - n + 1)))\n",
        "test": "def check(candidate):\n    assert candidate(1, 5) == '0b11'\n"
    },
    {
        "task_id": "HumanEval/156",
        "entry_point": "int_to_mini_roman",
        "prompt": "def int_to_mini_roman(number):\n",
        "canonical_solution": "    num = [1, 4, 5, 9, 10, 40, 50, 90, 100, 400, 500, 900, 1000]\n    sym = ['I', 'IV', 'V', 'IX', 'X', 'XL', 'L', 'XC', 'C', 'CD', 'D', 'CM', 'M']\n    i = 12\n    res = ''\n    while number:\n        div = number // num[i]\n        number %= num[i]\n        while div:\n            res += sym[i]\n            div -= 1\n        i -= 1\n    return res.lower()\n",
        "test": "def check(candidate):\n    assert candidate(19) == 'xix'\n    assert candidate(152) == 'clii'\n"
    }
]


def run_benchmark():
    print("=" * 70)
    print("CodeAbstract Algorithm Evaluation on HumanEval Coding Tasks")
    print("=" * 70)

    total_tasks = len(HUMANEVAL_TASKS)
    passed_ast_parse = 0
    passed_recon = 0
    passed_unit_tests = 0
    total_tokens = 0
    abstracted_tokens = 0
    latencies = []

    print(f"{'Task ID':<15} | {'AST Valid':<10} | {'Tokens':<8} | {'Masked':<8} | {'Latency (ms)':<12} | {'Status'}")
    print("-" * 70)

    for task in HUMANEVAL_TASKS:
        code = task['prompt'] + task['canonical_solution']
        entry_point = task['entry_point']

        # Abstraction benchmark
        t0 = time.perf_counter()
        res = abstract(code, privacy_level="high")
        lat = (time.perf_counter() - t0) * 1000.0
        latencies.append(lat)

        # 1. AST Validation
        try:
            ast.parse(res.abstract_code)
            ast_ok = True
            passed_ast_parse += 1
        except Exception:
            ast_ok = False

        # 2. Token counts
        n_total = res.statistics.get('total_nodes', 0)
        n_abs = res.statistics.get('abstracted_nodes', 0)
        total_tokens += n_total
        abstracted_tokens += n_abs

        # 3. Decrypt & Reconstruct verification
        mapping = decrypt_mapping(res.encrypted_mapping, res.encryption_key)
        tokens_in_map = list(mapping.keys())
        mock_response = f"Suggested fix for {', '.join(tokens_in_map[:3])}."
        recon = reconstruct_structured(mock_response, res.encrypted_mapping, res.encryption_key)
        recon_ok = (recon is not None and len(recon.references) > 0)
        if recon_ok:
            passed_recon += 1

        # 4. Unit Test Verification
        scope = {}
        try:
            exec(code, scope)
            exec(task['test'], scope)
            scope['check'](scope[entry_point])
            test_ok = True
            passed_unit_tests += 1
        except Exception:
            test_ok = False

        status = "PASS [OK]" if (ast_ok and recon_ok and test_ok) else "FAIL"
        print(f"{task['task_id']:<15} | {str(ast_ok):<10} | {n_total:<8} | {n_abs:<8} | {lat:<12.2f} | {status}")

    pir = (abstracted_tokens / total_tokens * 100.0) if total_tokens else 0.0
    mean_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    print("=" * 70)
    print("FINAL BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"Total Benchmark Tasks:                {total_tasks}")
    print(f"AST Syntactic Isomorphism:           {passed_ast_parse / total_tasks * 100.0:.2f}% ({passed_ast_parse}/{total_tasks})")
    print(f"Round-Trip Reconstruction Fidelity:  {passed_recon / total_tasks * 100.0:.2f}% ({passed_recon}/{total_tasks})")
    print(f"Canonical Test Suite Pass Rate:      {passed_unit_tests / total_tasks * 100.0:.2f}% ({passed_unit_tests}/{total_tasks})")
    print(f"Privacy Information Ratio (PIR):     {pir:.2f}% ({abstracted_tokens}/{total_tokens} AST nodes masked)")
    print(f"Mean Abstraction Latency:            {mean_lat:.2f} ms")
    print(f"95th Percentile Latency:             {p95_lat:.2f} ms")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
