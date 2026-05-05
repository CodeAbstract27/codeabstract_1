"""Tests for ENCRYPT/DECRYPT algorithm."""

import pytest
from cryptography.fernet import Fernet

from codeabstract.algorithms.encrypt import encrypt_mapping, decrypt_mapping


class TestEncrypt:
    """Test suite for Algorithm 4: ENCRYPT/DECRYPT."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting then decrypting should return original data."""
        original = {
            'FUNC_0': {'name': 'foo', 'label': 'IDENTIFIER', 'lineno': 1},
            'SECRET_0': {'name': 'api_key', 'label': 'SECRET', 'lineno': 2},
        }
        encrypted, key = encrypt_mapping(original)
        decrypted = decrypt_mapping(encrypted, key)
        assert decrypted == original

    def test_encrypt_returns_bytes(self):
        """Both encrypted data and key should be bytes."""
        mapping = {'X': 'Y'}
        encrypted, key = encrypt_mapping(mapping)
        assert isinstance(encrypted, bytes)
        assert isinstance(key, bytes)

    def test_encrypt_key_is_fernet(self):
        """Key should be a valid Fernet key (url-safe base64)."""
        mapping = {'test': 'value'}
        _, key = encrypt_mapping(mapping)
        # Should not raise
        Fernet(key)

    def test_decrypt_wrong_key_fails(self):
        """Decryption with wrong key should raise ValueError."""
        mapping = {'test': 'value'}
        encrypted, _ = encrypt_mapping(mapping)
        wrong_key = Fernet.generate_key()
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_mapping(encrypted, wrong_key)

    def test_decrypt_corrupted_data_fails(self):
        """Decryption of corrupted data should raise ValueError."""
        _, key = encrypt_mapping({'a': 'b'})
        with pytest.raises((ValueError, Exception)):
            decrypt_mapping(b"corrupted_data", key)

    def test_encrypt_empty_mapping(self):
        """Empty mapping should encrypt/decrypt successfully."""
        original = {}
        encrypted, key = encrypt_mapping(original)
        decrypted = decrypt_mapping(encrypted, key)
        assert decrypted == original

    def test_encrypt_unicode_data(self):
        """Unicode content should survive roundtrip."""
        original = {'token': {'name': 'données_privées', 'note': '🔒'}}
        encrypted, key = encrypt_mapping(original)
        decrypted = decrypt_mapping(encrypted, key)
        assert decrypted == original

    def test_each_call_generates_unique_key(self):
        """Each encrypt call should produce a different key."""
        mapping = {'a': 'b'}
        _, key1 = encrypt_mapping(mapping)
        _, key2 = encrypt_mapping(mapping)
        assert key1 != key2
