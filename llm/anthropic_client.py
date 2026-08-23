"""
Anthropic Claude LLM Client

Phase 4. The third of the providers ``pyproject.toml`` advertised and no
code implemented.

Claude takes the system instruction as a top-level parameter rather than a
message, and reports usage as ``input_tokens``/``output_tokens``; both are
normalised here so that downstream code — the audit log, the provider
comparison in :mod:`evaluation.providers` — never branches on vendor.
"""

from typing import Optional, Tuple

from llm.base import (
    DEFAULT_TIMEOUT,
    SYSTEM_PROMPT,
    BaseLLMClient,
    RetryPolicy,
    TokenUsage,
)

# Claude requires an explicit output cap.  Generous enough for a full code
# review, small enough that a runaway response cannot quietly cost a fortune.
MAX_OUTPUT_TOKENS = 4096


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude models via the ``anthropic`` package."""

    provider = "anthropic"
    default_model = "claude-sonnet-5"

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: Optional[RetryPolicy] = None,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ):
        super().__init__(api_key=api_key, model=model, timeout=timeout, retry=retry)
        self.max_output_tokens = max_output_tokens

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ImportError(
                "The Anthropic provider needs the 'anthropic' package: "
                "pip install 'codeabstract[anthropic]'"
            ) from exc

        # max_retries=0 for the same reason as the OpenAI client: one
        # retry policy for all providers, in llm.base.
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=0
        )

    def _generate(self, prompt: str) -> Tuple[str, TokenUsage]:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': prompt}],
        )

        # Content is a list of typed blocks; concatenate the text ones and
        # ignore any others rather than assuming block 0 is text.
        content = "".join(
            getattr(block, 'text', '')
            for block in getattr(message, 'content', [])
        )

        usage_data = getattr(message, 'usage', None)
        if usage_data is None:
            usage = TokenUsage()
        else:
            usage = TokenUsage(
                prompt_tokens=int(getattr(usage_data, 'input_tokens', 0) or 0),
                completion_tokens=int(getattr(usage_data, 'output_tokens', 0) or 0),
                reported=True,
            )

        return content, usage
