"""Tests for RECONSTRUCT(R, M̃, K) algorithm."""

import pytest

from codeabstract.algorithms.encrypt import encrypt_mapping
from codeabstract.algorithms.reconstruct import reconstruct


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
        assert 'Source Context' in result

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
