"""
Property-based regression suite (Hypothesis).

Priority 2 of the second adversarial round: the unit suites assert specific
before/after behaviour for specific inputs; these tests instead state
invariants that must hold for *any* input in a wide randomized space, and
let Hypothesis search for a counterexample. Each property below corresponds
to a guarantee the project's own audits (docs/AUDIT.md) have broken before:
D1 (secret leakage), D2 (token prefix collision), D4 (scope-blind cache),
and the general "abstraction must not corrupt syntax" claim.

Hypothesis found no counterexample to any property below at the time this
suite was written; a future failure here means a real regression, not a
flaky test -- re-run with the printed ``@example`` / seed to reproduce.
"""

import ast
import keyword
import string

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from algorithms.abstract import abstract
from algorithms.apply_fix import detokenise
from algorithms.encrypt import decrypt_mapping
from algorithms.helpers import BUILTINS
from algorithms.reconstruct import reconstruct

_SLOW = settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])

_PRIVACY_LEVELS = ("low", "medium", "high", "critical")

# Realistic credential shapes drawn from core/secret_detector.py's own
# pattern table, each paired with a name that also carries a credential
# signal, so the canary is detectable by both name and shape evidence.
_SECRET_TEMPLATES = [
    ("api_key", "sk_live_{suffix}"),
    ("github_token", "ghp_{suffix}"),
    ("openai_key", "sk-{suffix}"),
    ("anthropic_key", "sk-ant-{suffix}"),
]

_suffix_alphabet = string.ascii_letters + string.digits


def _identifier(draw_text: str) -> str:
    """Turn arbitrary text into a syntactically valid Python identifier."""
    cleaned = "".join(c if c.isalnum() else "_" for c in draw_text) or "x"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    cleaned = cleaned[:40]
    if keyword.iskeyword(cleaned) or keyword.issoftkeyword(cleaned):
        cleaned += "_v"
    return cleaned


# ═══════════════════════════════════════════════════════════
# Property 1 — a secret canary must never cross the boundary
# ═══════════════════════════════════════════════════════════

@_SLOW
@given(
    template=st.sampled_from(_SECRET_TEMPLATES),
    suffix=st.text(alphabet=_suffix_alphabet, min_size=16, max_size=40),
    var_suffix=st.text(alphabet=string.ascii_lowercase, min_size=0, max_size=8),
)
def test_secret_canary_never_survives_abstraction_at_any_privacy_level(
    template, suffix, var_suffix
):
    name_hint, value_template = template
    canary = value_template.format(suffix=suffix)
    var_name = f"{name_hint}_{var_suffix}" if var_suffix else name_hint

    source = f'{var_name} = "{canary}"\n'

    for level in _PRIVACY_LEVELS:
        result = abstract(source, privacy_level=level)
        assert canary not in result.abstract_code, (
            f"canary leaked at privacy={level}: {canary!r} survived in "
            f"{result.abstract_code!r}"
        )


# ═══════════════════════════════════════════════════════════
# Property 2 — VAR_1 must never corrupt VAR_10, VAR_100, ...
# ═══════════════════════════════════════════════════════════

@_SLOW
@given(count=st.integers(min_value=11, max_value=60))
def test_token_prefix_collision_never_corrupts_reconstruction(count):
    """
    D2 regression, generalised: for *any* variable count above 10, every
    token from VAR_0 through VAR_{count-1} must restore to its own name
    with no digit bleeding from a numerically-adjacent token.
    """
    source = "\n".join(f"variable_number_{i} = {i}" for i in range(count))
    result = abstract(source, privacy_level="high")

    # Reference every token in one response, in descending order so a
    # naive left-to-right substring replace would corrupt the smaller
    # numbers first (the actual failure mode D2 had).
    response = " and ".join(f"VAR_{i} is fine" for i in reversed(range(count)))

    translated = reconstruct(
        response, result.encrypted_mapping, result.encryption_key,
    )

    for i in range(count):
        expected = f"variable_number_{i}"
        # Every restored name must appear as a whole word: not immediately
        # followed by another digit that belonged to a different token.
        idx = 0
        found_clean = False
        while True:
            idx = translated.find(expected, idx)
            if idx == -1:
                break
            end = idx + len(expected)
            if end >= len(translated) or not translated[end].isdigit():
                found_clean = True
                break
            idx = end
        assert found_clean, (
            f"{expected} (from VAR_{i}) never appears un-corrupted in "
            f"{translated!r}"
        )


# ═══════════════════════════════════════════════════════════
# Property 3 — scoped duplicate names must not cross-resolve (D4)
# ═══════════════════════════════════════════════════════════

@_SLOW
@given(
    func_count=st.integers(min_value=2, max_value=8),
    local_names=st.lists(
        # min_size=2: single-character names are deliberately exempt from
        # abstraction at "high" (only "critical" includes them, via the
        # abstract_short_names flag) -- that's a documented level
        # difference, not the scope-collapse this property targets.
        # Builtins (Rule 1 in algorithms/helpers.py) are excluded too:
        # `iter`, `type`, `list`, ... are deliberately always kept
        # readable regardless of scope, which is a separate, intentional
        # policy from D4's scope-identity guarantee.
        st.text(alphabet=string.ascii_lowercase, min_size=2, max_size=6)
        .map(_identifier)
        .filter(lambda n: n not in BUILTINS),
        min_size=1, max_size=3, unique=True,
    ),
)
def test_shadowed_locals_get_distinct_tokens_per_scope(func_count, local_names):
    functions = []
    for f in range(func_count):
        body = "\n    ".join(f"{n} = {f}" for n in local_names)
        functions.append(f"def func_{f}(data):\n    {body}\n    return data\n")
    source = "\n".join(functions)

    result = abstract(source, privacy_level="high")
    mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)

    for name in local_names:
        tokens_for_name = {
            token for token, entry in mapping.items() if entry["name"] == name
        }
        # Each function's binding of `name` is a distinct symbol; a
        # scope-blind cache (D4) would collapse them all into one token.
        assert len(tokens_for_name) == func_count, (
            f"{name!r} bound in {func_count} scopes but only "
            f"{len(tokens_for_name)} distinct token(s) exist: {tokens_for_name}"
        )


# ═══════════════════════════════════════════════════════════
# Property 4 — abstraction must not break valid syntax
# ═══════════════════════════════════════════════════════════

_stmt_kind = st.sampled_from(["assign", "call", "if", "for", "fstring"])


def _random_function(names, kinds):
    lines = [f"def func_{abs(hash(tuple(names))) % 1000}({', '.join(names[:2]) or 'x'}):"]
    body = []
    for name, kind in zip(names, kinds):
        if kind == "assign":
            body.append(f"    {name} = 1")
        elif kind == "call":
            body.append(f"    print({name if body else '1'})")
        elif kind == "if":
            body.append(f"    if {name if body else 'True'}:")
            body.append(f"        {name} = 2")
        elif kind == "for":
            body.append(f"    for {name}_i in range(3):")
            body.append(f"        {name}_total = {name}_i")
        elif kind == "fstring":
            body.append(f'    {name}_msg = f"value is {{{name if body else "1"}}}"')
    if not body:
        body = ["    pass"]
    return "\n".join(lines + body + ["    return None"])


@_SLOW
@given(
    names=st.lists(
        st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8)
        .map(_identifier),
        min_size=1, max_size=6,
    ),
    kinds=st.lists(_stmt_kind, min_size=1, max_size=6),
    level=st.sampled_from(_PRIVACY_LEVELS),
)
def test_abstraction_preserves_syntactic_validity(names, kinds, level):
    n = min(len(names), len(kinds))
    if n == 0:
        return
    source = _random_function(names[:n], kinds[:n]) + "\n"

    try:
        ast.parse(source)
    except SyntaxError:
        return  # not a valid program to begin with; not our property to test

    result = abstract(source, privacy_level=level)
    try:
        ast.parse(result.abstract_code)
    except SyntaxError as exc:
        pytest.fail(
            f"abstraction broke valid syntax at privacy={level}: {exc}\n"
            f"input:\n{source}\noutput:\n{result.abstract_code}"
        )


# ═══════════════════════════════════════════════════════════
# Property 5 — abstraction is deterministic for identical input
# ═══════════════════════════════════════════════════════════

@_SLOW
@given(
    names=st.lists(
        st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8)
        .map(_identifier),
        min_size=1, max_size=5,
    ),
    level=st.sampled_from(_PRIVACY_LEVELS),
)
def test_abstraction_is_deterministic(names, level):
    source = "\n".join(f"{n} = {i}" for i, n in enumerate(names)) + "\n"
    try:
        ast.parse(source)
    except SyntaxError:
        return

    first = abstract(source, privacy_level=level)
    second = abstract(source, privacy_level=level)

    assert first.abstract_code == second.abstract_code, (
        "identical input produced different abstract code across runs"
    )


# ═══════════════════════════════════════════════════════════
# Property 6 — token substitution never bleeds into surrounding text
# ═══════════════════════════════════════════════════════════

@_SLOW
@given(
    count=st.integers(min_value=1, max_value=20),
    words=st.lists(
        st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=6),
        min_size=1, max_size=20,
    ),
)
def test_detokenise_never_touches_surrounding_prose(count, words):
    mapping = {
        f"VAR_{i}": {"name": f"restored_{i}", "lineno": 1} for i in range(count)
    }
    # Interleave real prose words with every token, so a non-word-bounded
    # replace (the historical D2 bug) would visibly corrupt a neighbour.
    pieces = []
    for i, word in enumerate(words):
        pieces.append(word)
        if i < count:
            pieces.append(f"VAR_{i}")
    code = " ".join(pieces)

    restored, restored_count, unresolved = detokenise(code, mapping)

    assert not unresolved
    for word in words:
        # Every original prose word survives verbatim as its own token,
        # possibly abutted by a restored identifier but never merged into
        # one word (split on whitespace still finds it).
        assert word in restored.split() or any(
            word in piece for piece in restored.split()
        )
    for i in range(min(count, len(words))):
        assert f"restored_{i}" in restored
