"""
Tests for llm/openai_client.py.

Previously untested. Mocks the ``openai`` SDK at the point the client
calls it.
"""

from unittest.mock import MagicMock, patch

import pytest

from llm.openai_client import OpenAIClient
from llm.base import RetryPolicy


def _completion(content, prompt_tokens=None, completion_tokens=None, usage=True):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    if usage:
        response.usage = MagicMock(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )
    else:
        response.usage = None
    return response


class TestOpenAIClient:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            OpenAIClient(api_key="")

    @patch("openai.OpenAI")
    def test_successful_send_normalises_usage(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _completion(
            "Bug is in FUNC_0.", prompt_tokens=100, completion_tokens=30,
        )
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient(api_key="sk-test")
        response = client.send("VAR_0 = FUNC_0()", task="debug")

        assert response.success is True
        assert response.content == "Bug is in FUNC_0."
        assert response.usage.prompt_tokens == 100
        assert response.usage.completion_tokens == 30
        assert response.usage.reported is True

    @patch("openai.OpenAI")
    def test_none_content_becomes_empty_string_not_none(self, mock_openai_cls):
        """
        A tool-call-only or moderation-refused completion returns
        ``message.content is None``. The client must not propagate a
        ``None`` where downstream code (audit log, reconstruct) expects a
        string.
        """
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _completion(None, usage=False)
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient(api_key="sk-test")
        response = client.send("code")

        assert response.success is True
        assert response.content == ""
        assert isinstance(response.content, str)

    @patch("openai.OpenAI")
    def test_api_key_never_appears_in_failure_message(self, mock_openai_cls):
        secret_key = "sk-REALSECRETVALUE0000000000000000000000000000"
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("401 unauthorized")
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient(api_key=secret_key, retry=RetryPolicy(max_attempts=1))
        response = client.send("code")

        assert response.success is False
        assert secret_key not in (response.error or "")

    @patch("openai.OpenAI")
    def test_system_prompt_is_sent_as_system_role(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _completion("ok")
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient(api_key="sk-test")
        client.send("VAR_0 = 1", task="review")

        _, kwargs = mock_client.chat.completions.create.call_args
        roles = [m["role"] for m in kwargs["messages"]]
        assert roles == ["system", "user"]

    @patch("openai.OpenAI")
    def test_transient_error_is_retried(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("503 service unavailable")
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient(
            api_key="sk-test",
            retry=RetryPolicy(max_attempts=3, sleep=lambda s: None),
        )
        response = client.send("code")

        assert response.success is False
        assert response.attempts == 3
