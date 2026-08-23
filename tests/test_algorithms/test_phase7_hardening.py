"""
Phase 7 hardening suite.

Regression tests for defects found by direct, adversarial testing rather
than by inspection: two false-classification bugs in the placeholder
regex (``core.secret_detector``), a silent-except path in evidence
pooling (``algorithms.abstract``), and larger-scale torture coverage of
the token-collision guard and AST round-tripping than the Phase 0/1
suites exercise.

As in the earlier phase suites, assertions are behavioural.
"""

import ast
import random
import warnings

import pytest

from algorithms.abstract import _aggregate_evidence_by_symbol, abstract
from algorithms.encrypt import decrypt_mapping
from algorithms.reconstruct import reconstruct
from core.secret_detector import is_placeholder, is_secret_value

ALL_LEVELS = ["low", "medium", "high", "critical"]


def _mapping(result):
    return decrypt_mapping(result.encrypted_mapping, result.encryption_key)


# ═══════════════════════════════════════════════════════════
# Placeholder regex — two bugs found in the same pattern
# ═══════════════════════════════════════════════════════════

class TestPlaceholderRegexHardening:
    """
    The old pattern was ``word[_\\-]?\\w*``: at most one separator, then
    only ``\\w`` (no further hyphens). Two failures followed from that:

    1. Multi-hyphen placeholders -- including the exact example in the
       module's own docstring -- failed to match and were scored as live
       secrets by the entropy path (a utility bug: real placeholders get
       redacted for no privacy benefit).
    2. Because the fix for (1) made the separator *optional*, any real
       secret value starting with the ordinary English words "my",
       "your", or "some" (a plausible naming accident, not a contrived
       one) matched the marker word alone and was exempted from secret
       detection entirely (a privacy bug: a live credential is never
       flagged).

    The final pattern requires the separator when there is trailing
    text, closing both without reopening the other.
    """

    @pytest.mark.parametrize("value", [
        "your-api-key-here",              # the module's own docstring example
        "your-api-key-2024-placeholder",
        "sample-token-value-v2-here",
        "example-secret-123-changeme",
        "your_api_key_here",
    ])
    def test_multiword_placeholders_are_recognised(self, value):
        assert is_placeholder(value) is True
        assert is_secret_value(value) is False

    @pytest.mark.parametrize("value", [
        "mySuperSecretProductionDatabasePassword2024xyz",
        "myAWSAccessKeySecret9f8a7b6c5d4e3f2a1b0c",
        "someInternalServiceApiToken8817263f5a9c",
        "YourCompanyStripeLiveKey20241108zzzabcxyz9",
    ])
    def test_real_secrets_starting_with_common_words_are_not_exempted(self, value):
        """
        A credential that happens to start with "my"/"your"/"some" must
        still be detected -- these are ordinary English words, not proof
        of a placeholder, and exempting them on sight was a live D1-class
        leak path through the entropy detector.
        """
        assert is_placeholder(value) is False
        assert is_secret_value(value) is True

    def test_end_to_end_placeholder_is_never_classified_secret(self):
        """
        The documented guarantee, exercised through the real pipeline.

        A binding name that is itself secret-suggestive ("api_key = ...")
        is deliberately exempt from this: Step 0/Tier 2's name-inherited
        SECRET label is meant to win regardless of the literal's shape --
        that is separate, correct "belt and suspenders" behaviour, tested
        in ``test_named_binding_still_forces_secret_even_for_placeholder``
        below. This test isolates the placeholder-suppression guarantee by
        using a binding name with no secret connotation of its own, so the
        only thing that could cause SECRET is the literal's own text.
        """
        mapping_by_level = {}
        for level in ALL_LEVELS:
            source = 'config_value = "your-api-key-2024-placeholder"\n'
            result = abstract(source, privacy_level=level)
            mapping = _mapping(result)
            mapping_by_level[level] = mapping
            secret_tokens = [t for t in mapping if t.startswith("SECRET_")]
            assert not secret_tokens, (
                f"placeholder classified SECRET at privacy_level={level}: {mapping}"
            )

        # At low/medium the value isn't abstracted at all (VALUE
        # abstraction is high/critical-only), so the placeholder text is
        # still directly visible in the output -- the strongest form of
        # "not treated as a secret".
        low_result = abstract('config_value = "your-api-key-2024-placeholder"\n', privacy_level="low")
        assert "your-api-key-2024-placeholder" in low_result.abstract_code

    def test_named_binding_still_forces_secret_even_for_placeholder(self):
        """
        The inverse: a secret-*named* binding must still redact its value
        even when that value happens to look like a placeholder. This is
        deliberate defense-in-depth (see algorithms.classify Step 0 /
        Tier 2) and must not regress while fixing the over-broad case
        above.
        """
        for level in ALL_LEVELS:
            source = 'api_key = "your-api-key-2024-placeholder"\n'
            result = abstract(source, privacy_level=level)
            assert "your-api-key-2024-placeholder" not in result.abstract_code, (
                f"leaked at privacy_level={level}"
            )

    def test_end_to_end_real_secret_starting_with_my_is_redacted(self):
        """The mirror case, through the real pipeline, at every level."""
        for level in ALL_LEVELS:
            source = (
                'config_value = "mySuperSecretProductionDatabasePassword2024xyz"\n'
            )
            result = abstract(source, privacy_level=level)
            assert "mySuperSecretProductionDatabasePassword2024xyz" not in result.abstract_code, (
                f"leaked at privacy_level={level}"
            )


# ═══════════════════════════════════════════════════════════
# Evidence pooling must not fail silently
# ═══════════════════════════════════════════════════════════

class TestEvidencePoolingFailsLoudly:
    """
    ``_aggregate_evidence_by_symbol`` used to swallow any exception from
    ``_symbol_key`` with a bare ``except: continue``. That is defensible
    as *behaviour* (one bad node should not crash the whole abstraction)
    but not as *silence*: the node's context evidence -- possibly a
    signal that a value is a credential -- disappears with no trace.
    """

    def test_symbol_key_failure_warns_instead_of_vanishing(self, monkeypatch):
        source = 'password = get_secret()\n'
        tree = ast.parse(source)
        from algorithms import abstract as abstract_module
        from core.context_features import analyze_context
        from core.symbol_table import build_scopes

        scopes = build_scopes(tree)
        context_evidence = analyze_context(tree)

        def _boom(node, name, scopes):
            raise ValueError("simulated resolver failure")

        monkeypatch.setattr(abstract_module, "_symbol_key", _boom)

        with pytest.warns(RuntimeWarning, match="_symbol_key failed"):
            pooled = _aggregate_evidence_by_symbol(tree, scopes, context_evidence)

        # The function must still return -- one node's evidence is lost,
        # but the whole abstraction does not crash over it.
        assert isinstance(pooled, dict)

    def test_normal_source_never_triggers_the_fallback(self):
        """
        The unguarded twin call at the main traversal site would crash on
        anything that reaches this branch, so on real source the warning
        must never fire.
        """
        source = '''
def handler(request):
    token = request.headers.get("Authorization")
    if token == expected_token:
        return True
    return False
'''
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            abstract(source, privacy_level="critical")  # must not raise


# ═══════════════════════════════════════════════════════════
# Collision-safety at scale
# ═══════════════════════════════════════════════════════════

class TestCollisionSafetyAtScale:
    """
    The Phase 0 suite proves the guard on ~25 identifiers. This drives it
    with hundreds, in the specific adjacency patterns most likely to
    expose an off-by-one in a hand-rolled word-boundary scheme: every
    token immediately next to a numeric extension of itself, in a single
    shuffled response so ordering cannot mask a bug.
    """

    def test_five_hundred_identifiers_round_trip_without_corruption(self):
        n = 500
        source = "\n".join(f"identifier_{i} = {i}" for i in range(n))
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)

        var_tokens = [t for t in mapping if t.startswith("VAR_")]
        assert len(var_tokens) >= n * 0.9, "expected most identifiers to tokenise"

        # Deliberately adversarial ordering: every token directly adjacent
        # to a numeric extension of itself (VAR_1VAR_10 etc. would corrupt
        # under a naive shortest-match-first substitution), separated only
        # by punctuation an LLM would plausibly use, not friendly spacing.
        rng = random.Random(1234)
        shuffled = list(var_tokens)
        rng.shuffle(shuffled)
        response = ",".join(shuffled) + "." + "".join(
            f"({t})" for t in shuffled[:50]
        )

        translated = reconstruct(response, result.encrypted_mapping, result.encryption_key)
        body = translated.split("Source Context")[0] if "Source Context" in translated else translated

        # Every one of the 500 tokens must resolve to exactly its own name
        # -- the precise check; a corrupted substitution would either
        # miss an expected "(name) (line N)" pair or produce one for a
        # name that was never assigned that token.
        for token in shuffled:
            expected_name = mapping[token]["name"]
            assert f"{expected_name} (line" in body, f"{token} lost or corrupted its name"

    @pytest.mark.parametrize("base,extensions", [
        (1, [10, 100, 1000]),
        (2, [20, 200, 2000]),
        (9, [90, 900, 9000]),
    ])
    def test_specific_prefix_extension_families_never_cross_contaminate(self, base, extensions):
        all_n = [base] + extensions
        source = "\n".join(f"identifier_{i} = {i}" for i in all_n)
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)
        var_tokens = sorted(
            (t for t in mapping if t.startswith("VAR_")),
            key=lambda t: int(t.split("_")[1]),
        )
        assert len(var_tokens) == len(all_n)

        response = " next to ".join(var_tokens)
        translated = reconstruct(response, result.encrypted_mapping, result.encryption_key)
        body = translated.split("Source Context")[0] if "Source Context" in translated else translated

        for token in var_tokens:
            assert f"{mapping[token]['name']} (line" in body


# ═══════════════════════════════════════════════════════════
# AST round-tripping on constructs the Phase 0/1 suites don't cover
# ═══════════════════════════════════════════════════════════

WALRUS_SOURCE = '''
def process(items):
    results = []
    while (chunk := items.pop() if items else None) is not None:
        results.append(chunk * 2)
    return results
'''

MATCH_SOURCE = '''
def dispatch(command):
    match command.split():
        case ["go", direction]:
            return f"moving {direction}"
        case ["look"]:
            return "looking around"
        case [action, *rest] if action == "use":
            return f"using {rest}"
        case _:
            return "unknown"
'''

POSITIONAL_ONLY_SOURCE = '''
def compute(x, y, /, z, *, scale=1, **extra):
    return (x + y + z) * scale
'''

ASYNC_GENERATOR_SOURCE = '''
import asyncio

async def stream_events(source):
    async for event in source:
        if event.kind == "heartbeat":
            continue
        yield event.payload

async def collect(source):
    return [item async for item in stream_events(source)]
'''

NESTED_FSTRING_SOURCE = '''
def render(user, items):
    label = f"{user.name}: {', '.join(f'{i.name}={i.value!r}' for i in items)}"
    return label
'''

DECORATED_CLASS_SOURCE = '''
from functools import wraps

def retry(times=3):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(times):
                try:
                    return fn(*args, **kwargs)
                except ConnectionError:
                    continue
            raise RuntimeError("exhausted retries")
        return wrapper
    return decorator

class ApiClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self._api_key = api_key

    @retry(times=5)
    def fetch(self, path):
        return f"{self.base_url}/{path}?key={self._api_key}"
'''

TYPE_GENERIC_SOURCE = '''
from typing import Dict, List, Optional

def merge(left: Dict[str, List[int]], right: Optional[Dict[str, List[int]]] = None) -> Dict[str, List[int]]:
    right = right or {}
    out: Dict[str, List[int]] = dict(left)
    for key, values in right.items():
        out.setdefault(key, []).extend(values)
    return out
'''

EXOTIC_SOURCES = {
    "walrus": WALRUS_SOURCE,
    "match_statement": MATCH_SOURCE,
    "positional_only_params": POSITIONAL_ONLY_SOURCE,
    "async_generator": ASYNC_GENERATOR_SOURCE,
    "nested_fstring": NESTED_FSTRING_SOURCE,
    "decorated_class": DECORATED_CLASS_SOURCE,
    "type_generics": TYPE_GENERIC_SOURCE,
}


class TestExoticSyntaxRoundTrips:

    @pytest.mark.parametrize("name,source", EXOTIC_SOURCES.items(), ids=list(EXOTIC_SOURCES))
    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_abstracts_to_valid_python(self, name, source, level):
        result = abstract(source, privacy_level=level)
        ast.parse(result.abstract_code)  # raises SyntaxError on failure

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_decorated_class_round_trips_through_reconstruct(self, level):
        """
        The one exotic fixture with enough named identifiers to make a
        real round trip worth checking: decorators, nested closures, and
        an instance attribute all have to survive ABSTRACT -> RECONSTRUCT
        together, not just parse.
        """
        result = abstract(DECORATED_CLASS_SOURCE, privacy_level=level)
        ast.parse(result.abstract_code)
        mapping = _mapping(result)

        tokens = list(mapping.keys())
        if not tokens:
            pytest.skip(f"nothing tokenised at privacy_level={level}")

        response = "Review " + ", ".join(tokens)
        translated = reconstruct(response, result.encrypted_mapping, result.encryption_key)
        for token in tokens:
            expected_name = mapping[token]["name"]
            assert expected_name in translated, f"{token} ({expected_name}) lost in reconstruction"
