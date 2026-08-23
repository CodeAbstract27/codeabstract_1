"""
Google Gemini LLM Client

Phase 4: refactored onto :class:`llm.base.BaseLLMClient`. Prompt assembly,
retries, timing and token accounting moved to the base class; what remains
here is the one call that is actually Gemini-specific.

The SDK is imported lazily so that ``import llm`` works with only one
vendor package installed — the common case, since a user configures the
provider they have a key for.
"""

from typing import Optional, Tuple

from llm.base import (
    DEFAULT_TIMEOUT,
    SYSTEM_PROMPT,
    BaseLLMClient,
    RetryPolicy,
    TokenUsage,
)

# Re-exported for callers that imported them from this module before
# Phase 4 moved them to llm.base.
from llm.base import TASK_PROMPTS, LLMResponse  # noqa: F401


class GeminiClient(BaseLLMClient):
    """Google Gemini via ``google-generativeai``."""

    provider = "gemini"
    default_model = "gemini-2.5-flash"

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: Optional[RetryPolicy] = None,
    ):
        super().__init__(api_key=api_key, model=model, timeout=timeout, retry=retry)

        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ImportError(
                "The Gemini provider needs the 'google-generativeai' package: "
                "pip install 'codeabstract[gemini]'"
            ) from exc

        genai.configure(api_key=api_key)
        self._client = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=SYSTEM_PROMPT,
        )

    def _generate(self, prompt: str) -> Tuple[str, TokenUsage]:
        response = self._client.generate_content(
            prompt,
            request_options={'timeout': self.timeout},
        )

        meta = getattr(response, 'usage_metadata', None)
        if meta is None:
            usage = TokenUsage()
        else:
            usage = TokenUsage(
                prompt_tokens=int(getattr(meta, 'prompt_token_count', 0) or 0),
                completion_tokens=int(getattr(meta, 'candidates_token_count', 0) or 0),
                reported=True,
            )

        return response.text, usage
