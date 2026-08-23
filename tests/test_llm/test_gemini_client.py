"""
Unit tests for llm/gemini_client.py

Tests Gemini client initialization, prompt handling, API consultation mocking, and error handling.
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from llm.gemini_client import GeminiClient, LLMResponse, TASK_PROMPTS, SYSTEM_PROMPT


def test_llm_response_dataclass():
    """LLMResponse dataclass should correctly store attributes."""
    resp = LLMResponse(content="sample content", response_time=1.2, success=True)
    assert resp.content == "sample content"
    assert resp.response_time == 1.2
    assert resp.success is True
    assert resp.error is None


@patch("google.generativeai.GenerativeModel")
@patch("google.generativeai.configure")
def test_consult_gemini_success(mock_configure, mock_model_class, monkeypatch):
    """TC-LLM-04: Successful consultation returns generated text response."""
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key")
    
    # Setup mock response
    mock_response = MagicMock()
    mock_response.text = "The issue is in FUNC_0."
    mock_instance = MagicMock()
    mock_instance.generate_content.return_value = mock_response
    mock_model_class.return_value = mock_instance

    client = GeminiClient(api_key="mock_key")
    response = client.send("FUNC_0 code string", task="review")

    assert response.success is True
    assert response.content == "The issue is in FUNC_0."
    assert response.response_time >= 0


@patch("google.generativeai.GenerativeModel")
@patch("google.generativeai.configure")
def test_consult_gemini_api_error(mock_configure, mock_model_class, monkeypatch):
    """TC-LLM-05: API exception should return LLMResponse with success=False."""
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key")
    
    mock_instance = MagicMock()
    mock_instance.generate_content.side_effect = Exception("Quota exceeded")
    mock_model_class.return_value = mock_instance

    client = GeminiClient(api_key="mock_key")
    response = client.send("FUNC_0 code string", task="review")

    assert response.success is False
    assert response.content == ""
    assert "Quota exceeded" in response.error
