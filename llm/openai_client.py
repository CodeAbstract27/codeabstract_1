"""
OpenAI LLM Client

Phase 4. ``pyproject.toml`` has advertised an ``openai`` extra since the
first release; this is the code that finally makes installing it do
something.

Uses the Chat Completions endpoint, which every 1.x and 2.x release of the
SDK supports — the tool asks one question and reads one answer, so there is
nothing to gain from a newer, narrower API surface.
"""

from typing import Optional, Tuple

from llm.base import (
    DEFAULT_TIMEOUT,
    SYSTEM_PROMPT,
    BaseLLMClient,
    RetryPolicy,
    TokenUsage,
)


class OpenAIClient(BaseLLMClient):
    """OpenAI chat models via the ``openai`` package."""

    provider = "openai"
    default_model = "gpt-4o"

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: Optional[RetryPolicy] = None,
    ):
        super().__init__(api_key=api_key, model=model, timeout=timeout, retry=retry)

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ImportError(
                "The OpenAI provider needs the 'openai' package: "
                "pip install 'codeabstract[openai]'"
            ) from exc

        # max_retries=0: the base class owns the retry policy, so that all
        # three providers back off identically and the audit log's attempt
        # count means the same thing everywhere.
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    def _generate(self, prompt: str) -> Tuple[str, TokenUsage]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
        )

        content = response.choices[0].message.content or ""

        usage_data = getattr(response, 'usage', None)
        if usage_data is None:
            usage = TokenUsage()
        else:
            usage = TokenUsage(
                prompt_tokens=int(getattr(usage_data, 'prompt_tokens', 0) or 0),
                completion_tokens=int(getattr(usage_data, 'completion_tokens', 0) or 0),
                reported=True,
            )

        return content, usage
