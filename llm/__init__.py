"""
LLM Client Factory

Creates the right client based on provider name.
"""

from llm.gemini_client import GeminiClient

def create_client(api_key: str) -> GeminiClient:
    """
    Factory function to create a Gemini LLM client.

    Args:
        api_key: Gemini API key.

    Returns:
        Configured Gemini LLM client.
    """
    return GeminiClient(api_key=api_key)
