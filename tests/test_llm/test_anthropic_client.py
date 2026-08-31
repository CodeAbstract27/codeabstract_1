"""
Tests for llm/anthropic_client.py.

Previously untested. Mocks the ``anthropic`` SDK at the point the client
calls it, so these exercise the client's own logic (usage normalisation,
content-block concatenation, retry wiring) without a network call.
"""

from unittest.mock import MagicMock, patch

import pytest

from llm.anthropic_client import AnthropicClient
from llm.base import RetryPolicy


def _text_block(text):
    block = MagicMock()
    block.text = text
    return block


class TestAnthropicClient:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            AnthropicClient(api_key="")

    @patch("anthropic.Anthropic")
    def test_successful_send_normalises_usage(self, mock_anthropic_cls):
        message = MagicMock()
        message.content = [_text_block("Bug is in FUNC_0.")]
        message.usage = MagicMock(input_tokens=120, output_tokens=40)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = message
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient(api_key="sk-ant-test")
        response = client.send("VAR_0 = FUNC_0()", task="debug")

        assert response.success is True
        assert response.content == "Bug is in FUNC_0."
        assert response.usage.prompt_tokens == 120
        assert response.usage.completion_tokens == 40
        assert response.usage.reported is True
        assert response.provider == "anthropic"

    @patch("anthropic.Anthropic")
    def test_multiple_content_blocks_are_concatenated(self, mock_anthropic_cls):
        message = MagicMock()
        message.content = [_text_block("Part one. "), _text_block("Part two.")]
        message.usage = None

        mock_client = MagicMock()
        mock_client.messages.create.return_value = message
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient(api_key="sk-ant-test")
        response = client.send("code")

        assert response.content == "Part one. Part two."
        assert response.usage.reported is False

    @patch("anthropic.Anthropic")
    def test_non_text_block_is_ignored_not_crashed_on(self, mock_anthropic_cls):
        """
        A tool-use or thinking block has no ``.text`` attribute. The client
        must skip it, not raise, since content really can be mixed blocks.
        """
        tool_block = MagicMock(spec=[])  # no attributes at all
        message = MagicMock()
        message.content = [tool_block, _text_block("answer")]
        message.usage = None

        mock_client = MagicMock()
        mock_client.messages.create.return_value = message
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient(api_key="sk-ant-test")
        response = client.send("code")

        assert response.success is True
        assert response.content == "answer"

    @patch("anthropic.Anthropic")
    def test_api_key_never_appears_in_failure_message(self, mock_anthropic_cls):
        """
        The client wraps whatever the SDK raises into ``response.error``.
        If a transport-level error object happened to repr() the request
        (auth header included), that text must not leak the key.
        """
        secret_key = "sk-ant-api03-REALSECRETVALUE0000000000000000"
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("401 unauthorized")
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient(
            api_key=secret_key, retry=RetryPolicy(max_attempts=1),
        )
        response = client.send("code")

        assert response.success is False
        assert secret_key not in (response.error or "")

    @patch("anthropic.Anthropic")
    def test_transient_error_is_retried_non_transient_is_not(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("rate limit exceeded")
        mock_anthropic_cls.return_value = mock_client

        sleeps = []
        client = AnthropicClient(
            api_key="sk-ant-test",
            retry=RetryPolicy(max_attempts=3, sleep=sleeps.append),
        )
        response = client.send("code")

        assert response.success is False
        assert response.attempts == 3
        assert mock_client.messages.create.call_count == 3

    @patch("anthropic.Anthropic")
    def test_bad_request_is_not_retried(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("400 invalid request")
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient(
            api_key="sk-ant-test",
            retry=RetryPolicy(max_attempts=3, sleep=lambda s: None),
        )
        response = client.send("code")

        assert response.attempts == 1
        assert mock_client.messages.create.call_count == 1
