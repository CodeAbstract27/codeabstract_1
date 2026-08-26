"""Tests for RECONSTRUCT(R, M̃, K) algorithm."""

import pytest

from algorithms.encrypt import encrypt_mapping
from algorithms.reconstruct import reconstruct


class TestReconstruct:
    """Test suite for Algorithm 3: RECONSTRUCT(R, M̃, K)."""

    def _make_encrypted(self, mapping):
        """Helper to create encrypted mapping + key."""
        return encrypt_mapping(mapping)

    def test_reconstruct_replaces_tokens(self):
        """Tokens should be replaced with original names."""
        mapping = {
            'FUNC_0': {
                'name': 'calculate_commission',
                'label': 'IDENTIFIER',
                'lineno': 5,
                'ctx': {'snippet': 'def calculate_commission(amount):', 'start_line': 5, 'end_line': 5, 'target_line': 5},
            },
        }
        enc, key = self._make_encrypted(mapping)
        response = "Bug found in FUNC_0 at line 5"
        result = reconstruct(response, enc, key)
        assert 'calculate_commission' in result
        assert 'FUNC_0' not in result

    def test_reconstruct_multiple_tokens(self):
        """Multiple different tokens should all be replaced."""
        mapping = {
            'FUNC_0': {'name': 'process', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}},
            'VAR_0': {'name': 'data', 'label': 'IDENTIFIER', 'lineno': 2, 'ctx': {}},
            'SECRET_0': {'name': 'api_key', 'label': 'SECRET', 'lineno': 3, 'ctx': {}},
        }
        enc, key = self._make_encrypted(mapping)
        response = "FUNC_0 uses VAR_0 and SECRET_0"
        result = reconstruct(response, enc, key)
        assert 'process' in result
        assert 'data' in result
        assert 'api_key' in result
        assert 'FUNC_0' not in result

    def test_reconstruct_preserves_unknown_tokens(self):
        """Tokens not in mapping should remain unchanged."""
        mapping = {
            'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}},
        }
        enc, key = self._make_encrypted(mapping)
        response = "Check FUNC_0 and FUNC_99"
        result = reconstruct(response, enc, key)
        assert 'foo' in result
        assert 'FUNC_99' in result  # Unknown token preserved

    def test_reconstruct_adds_context_blocks(self):
        """Context blocks should be appended when available."""
        mapping = {
            'VAR_0': {
                'name': 'commission_rate',
                'label': 'VALUE',
                'lineno': 3,
                'ctx': {
                    'snippet': 'commission_rate = 0.029',
                    'start_line': 3,
                    'end_line': 3,
                    'target_line': 3,
                },
            },
        }
        enc, key = self._make_encrypted(mapping)
        response = "VAR_0 should be higher"
        result = reconstruct(response, enc, key)
        assert 'commission_rate' in result
        assert 'line 3' in result
        assert 'Source References' in result

    def test_reconstruct_no_tokens(self):
        """Response with no tokens should be returned unchanged."""
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = self._make_encrypted(mapping)
        response = "This response has no tokens at all."
        result = reconstruct(response, enc, key)
        assert result == response

    def test_reconstruct_repeated_token(self):
        """Same token appearing multiple times should all be replaced."""
        mapping = {
            'FUNC_0': {'name': 'calculate', 'label': 'IDENTIFIER', 'lineno': 5, 'ctx': {}},
        }
        enc, key = self._make_encrypted(mapping)
        response = "FUNC_0 calls FUNC_0 recursively"
        result = reconstruct(response, enc, key)
        # 2 replacements in text + 1 in context block header = 3
        assert result.count('calculate') >= 2
        assert 'FUNC_0' not in result

    def test_reconstruct_wrong_key_fails(self):
        """Using wrong key should raise ValueError."""
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = self._make_encrypted(mapping)
        from cryptography.fernet import Fernet
        wrong_key = Fernet.generate_key()
        with pytest.raises(ValueError, match="Decryption failed"):
            reconstruct("FUNC_0", enc, wrong_key)


# ═══════════════════════════════════════════════════════════
# Additional gap-filling tests
# ═══════════════════════════════════════════════════════════

class TestReconstructTokenExtraction:
    """Tests for the _extract_tokens private helper via reconstruct()."""

    def _enc(self, mapping):
        return encrypt_mapping(mapping)

    def test_extracts_func_token(self):
        """FUNC_ tokens must be found and replaced."""
        mapping = {'FUNC_0': {'name': 'process', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = self._enc(mapping)
        result = reconstruct("FUNC_0 is broken", enc, key)
        assert "process" in result
        assert "FUNC_0" not in result

    def test_extracts_var_token(self):
        """VAR_ tokens must be found and replaced."""
        mapping = {'VAR_5': {'name': 'commission_rate', 'label': 'VALUE', 'lineno': 10, 'ctx': {}}}
        enc, key = self._enc(mapping)
        result = reconstruct("Check VAR_5 value", enc, key)
        assert "commission_rate" in result

    def test_extracts_secret_token(self):
        """SECRET_ tokens must be found and replaced."""
        mapping = {'SECRET_0': {'name': 'api_key', 'label': 'SECRET', 'lineno': 3, 'ctx': {}}}
        enc, key = self._enc(mapping)
        result = reconstruct("SECRET_0 is exposed", enc, key)
        assert "api_key" in result

    def test_extracts_const_token(self):
        """CONST_ tokens must be found and replaced."""
        mapping = {'CONST_2': {'name': '0.029', 'label': 'VALUE', 'lineno': 5, 'ctx': {}}}
        enc, key = self._enc(mapping)
        result = reconstruct("CONST_2 is the rate", enc, key)
        assert "0.029" in result

    def test_extracts_class_token(self):
        """CLASS_ tokens are NOT extracted by _extract_tokens (pattern doesn't match CLASS_)."""
        # CLASS_ is not in the regex pattern → should remain unchanged
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = self._enc(mapping)
        result = reconstruct("CLASS_0 has a bug in FUNC_0", enc, key)
        # CLASS_0 is unknown → preserved; FUNC_0 → replaced
        assert "CLASS_0" in result
        assert "foo" in result

    def test_deduplication_single_context_block(self):
        """Same token appearing twice should produce only one context block."""
        mapping = {
            'FUNC_0': {'name': 'calculate', 'label': 'IDENTIFIER', 'lineno': 5,
                       'ctx': {'snippet': 'def calculate():', 'start_line': 5,
                               'end_line': 5, 'target_line': 5}},
        }
        enc, key = self._enc(mapping)
        # 'FUNC_0' appears twice → deduplicated → one context block
        result = reconstruct("FUNC_0 calls FUNC_0", enc, key)
        assert result.count("Source References") == 1

    def test_no_tokens_in_response(self):
        """Response with no tokens should be returned verbatim."""
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = self._enc(mapping)
        original = "Everything looks good, no issues found."
        result = reconstruct(original, enc, key)
        assert result == original

    def test_token_not_in_response_pattern(self):
        """Partial token names like 'FUNC' (without _N) must NOT be matched."""
        mapping = {'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}}}
        enc, key = self._enc(mapping)
        result = reconstruct("FUNC is a prefix not a token", enc, key)
        # 'FUNC' alone should not trigger replacement
        assert "foo" not in result
        assert "FUNC" in result


class TestReconstructContextFormatting:
    """Tests for context block formatting."""

    def _enc(self, mapping):
        return encrypt_mapping(mapping)

    def test_context_block_shows_arrow_on_target_line(self):
        """The target line should be marked with → in context block.

        Only tokens with significant prefixes (FUNC, CLASS, SECRET) get
        full context blocks with arrow markers.  VAR tokens go into the
        compact 'Other referenced identifiers' list instead.
        """
        mapping = {
            'FUNC_0': {
                'name': 'calculate_commission',
                'label': 'IDENTIFIER',
                'lineno': 3,
                'ctx': {
                    'snippet': 'line1\nline2\ndef calculate_commission(amount):\nline4\nline5',
                    'start_line': 1,
                    'end_line': 5,
                    'target_line': 3,
                },
            },
        }
        enc, key = self._enc(mapping)
        result = reconstruct("FUNC_0 is the issue", enc, key)
        assert "→" in result
        assert "def calculate_commission(amount):" in result

    def test_context_block_shows_no_context_when_empty(self):
        """When ctx is empty dict, context block should say 'no context available'."""
        mapping = {
            'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1, 'ctx': {}},
        }
        enc, key = self._enc(mapping)
        result = reconstruct("FUNC_0 is broken", enc, key)
        assert "no context available" in result

    def test_multiple_context_blocks_appended(self):
        """Multiple tokens should produce multiple context block entries."""
        mapping = {
            'FUNC_0': {'name': 'process', 'label': 'IDENTIFIER', 'lineno': 5,
                       'ctx': {'snippet': 'def process():', 'start_line': 5,
                               'end_line': 5, 'target_line': 5}},
            'VAR_0': {'name': 'commission', 'label': 'VALUE', 'lineno': 10,
                      'ctx': {'snippet': 'commission = 0.05', 'start_line': 10,
                              'end_line': 10, 'target_line': 10}},
        }
        enc, key = self._enc(mapping)
        result = reconstruct("Fix FUNC_0 and check VAR_0", enc, key)
        assert "process" in result
        assert "commission" in result
        assert result.count("line") >= 2  # two different line references


class TestReconstructMultilineResponse:
    """Tokens embedded in multi-line LLM responses must all be replaced."""

    def _enc(self, mapping):
        return encrypt_mapping(mapping)

    def test_tokens_in_code_block(self):
        """Tokens inside a markdown code block must be replaced."""
        mapping = {
            'FUNC_0': {'name': 'calculate', 'label': 'IDENTIFIER', 'lineno': 5, 'ctx': {}},
        }
        enc, key = self._enc(mapping)
        response = "```python\ndef FUNC_0(x):\n    return x\n```"
        result = reconstruct(response, enc, key)
        assert "calculate" in result
        assert "FUNC_0" not in result

    def test_large_response_with_many_tokens(self):
        """All tokens in a large multi-token response should be replaced."""
        mapping = {f"FUNC_{i}": {'name': f"fn_{i}", 'label': 'IDENTIFIER',
                                  'lineno': i, 'ctx': {}}
                   for i in range(10)}
        enc, key = self._enc(mapping)
        response = " ".join(f"FUNC_{i}" for i in range(10))
        result = reconstruct(response, enc, key)
        for i in range(10):
            assert f"fn_{i}" in result
            assert f"FUNC_{i}" not in result
