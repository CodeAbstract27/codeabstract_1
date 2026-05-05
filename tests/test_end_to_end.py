"""End-to-end integration test for full CodeAbstract workflow."""

import pytest
from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct
from algorithms.encrypt import encrypt_mapping, decrypt_mapping


class TestEndToEnd:

    def test_full_workflow(self):
        """Abstract → simulate LLM → reconstruct → verify."""
        source = '''
STRIPE_KEY = "sk_live_abc123"
commission_rate = 0.029

def calculate_commission(amount):
    return amount * commission_rate
'''
        # Step 1: Abstract
        result = abstract(source, privacy_level="high")
        assert result.abstract_code
        assert 'STRIPE_KEY' not in result.abstract_code

        # Step 2: Verify mapping works
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
        assert len(mapping) > 0

        # Step 3: Simulate LLM response using actual tokens
        tokens = list(mapping.keys())
        llm_response = f"Bug in {tokens[0]}: check the logic"

        # Step 4: Reconstruct
        translated = reconstruct(
            llm_response, result.encrypted_mapping, result.encryption_key,
        )

        # Step 5: Verify original name appears
        expected_name = mapping[tokens[0]]['name']
        assert expected_name in translated
        assert tokens[0] not in translated

    def test_roundtrip_all_token_types(self):
        """Ensure all token types survive the roundtrip."""
        source = '''
API_KEY = "sk_live_secret123"
base_url = "https://api.example.com"

def process(data):
    return data
'''
        result = abstract(source, privacy_level="high")
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)

        # Build response using all tokens
        response_parts = [f"Reviewing {t}" for t in mapping.keys()]
        llm_response = ". ".join(response_parts)

        translated = reconstruct(
            llm_response, result.encrypted_mapping, result.encryption_key,
        )

        # All original names should appear
        for entry in mapping.values():
            assert entry['name'] in translated

    def test_empty_source(self):
        """Empty source should produce empty abstract code."""
        result = abstract("", privacy_level="high")
        assert result.abstract_code == ""
        assert result.statistics['abstracted_nodes'] == 0
