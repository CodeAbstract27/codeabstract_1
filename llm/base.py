"""
Provider-Agnostic LLM Client Interface

Phase 4 — the "provider abstraction" workstream.

``pyproject.toml`` has advertised ``openai`` and ``anthropic`` extras since
the first release, and no code imported either. Only Gemini existed, behind
a factory whose signature took no provider argument at all. The packaging
described a system that was never built.

This module holds the parts that are genuinely common to every provider, so
that adding one is a matter of writing a ``_generate`` method rather than
re-implementing the surrounding machinery:

* **The prompt.** One system instruction and one task table, shared, so an
  answer's shape does not depend on which vendor produced it. A comparison
  across providers is only meaningful if they were asked the same thing.
* **Retries and timeouts.** Transient failures (rate limits, 5xx, dropped
  connections) are retried with exponential backoff; a bad request is not,
  because retrying it just spends the quota again for the same error.
* **Token accounting.** Every provider reports usage differently and some
  omit it. :class:`TokenUsage` normalises the three shapes into one, and
  records ``reported=False`` when a provider told us nothing rather than
  quietly writing zeros into the audit log.

The one deliberate constraint on every implementation: **the client is
handed abstract code and never sees the original**. Providers are
constructed with an already-abstracted payload by the calling command, so
there is no code path here that could send raw source anywhere.
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Protocol, Tuple, runtime_checkable

# ═══════════════════════════════════════════════════════════
# Shared prompt
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are an expert code reviewer.
The code uses abstract identifiers (FUNC_0, VAR_1, CLASS_0)
for privacy. Use these exact names in your response.
Reference specific line numbers when pointing out issues."""

TASK_PROMPTS: Dict[str, str] = {
    'debug': "Find bugs and errors in this code:\n\n```{language}\n{code}\n```",
    'review': "Review this code for quality and issues:\n\n```{language}\n{code}\n```",
    'optimize': "Suggest optimizations for this code:\n\n```{language}\n{code}\n```",
    'security': "Find security issues in this code:\n\n```{language}\n{code}\n```",
    'explain': "Explain what this code does:\n\n```{language}\n{code}\n```",
}

# Phase 4: the proposal's input specification has "User Query" as a
# first-class field.  A free-form question is wrapped in the same envelope
# as a preset so the two are indistinguishable to the model.
FREEFORM_PROMPT = "{query}\n\n```{language}\n{code}\n```"


def build_prompt(
    code: str,
    task: str = "review",
    query: Optional[str] = None,
    language: str = "python",
) -> str:
    """
    Assemble the user-turn prompt.

    Args:
        code: Abstract code. Never the original — see the module docstring.
        task: One of :data:`TASK_PROMPTS`; ignored when *query* is given.
        query: A free-form question. **Must already be abstracted** by
            :mod:`core.query_abstractor` — a question naming the very
            identifiers the code hides would undo the abstraction in the
            same request.
        language: Fence language hint.

    Returns:
        The prompt string.
    """
    if query and query.strip():
        return FREEFORM_PROMPT.format(query=query.strip(), code=code, language=language)

    template = TASK_PROMPTS.get(task, TASK_PROMPTS['review'])
    return template.format(code=code, language=language)


# ═══════════════════════════════════════════════════════════
# Results
# ═══════════════════════════════════════════════════════════

@dataclass
class TokenUsage:
    """
    Normalised token counts for one request.

    ``reported`` distinguishes "this request used no tokens" from "this
    provider did not tell us". The audit log records the difference,
    because a compliance record showing 0 tokens for a request that
    actually sent 4,000 is worse than one that says the count is unknown.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reported: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> Dict:
        return {
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'reported': self.reported,
        }


@dataclass
class LLMResponse:
    """
    One provider's answer.

    The first four fields are the pre-Phase-4 shape and keep their meaning,
    so existing callers (``commands/review_cmd.py``, ``evaluation``) work
    unchanged. The rest is what a multi-provider tool needs to be able to
    say afterwards *which* model answered and what it cost.
    """

    content: str
    response_time: float
    success: bool
    error: Optional[str] = None
    provider: str = "unknown"
    model: str = "unknown"
    usage: TokenUsage = field(default_factory=TokenUsage)
    attempts: int = 1

    def to_dict(self) -> Dict:
        return {
            'provider': self.provider,
            'model': self.model,
            'success': self.success,
            'error': self.error,
            'response_time': round(self.response_time, 4),
            'attempts': self.attempts,
            'usage': self.usage.to_dict(),
        }


@runtime_checkable
class LLMClient(Protocol):
    """
    What every provider implementation exposes.

    Deliberately small. Anything richer — streaming, tool use, structured
    output — differs enough between vendors that a common abstraction would
    be a lie, and none of it is needed to ask "review this code".
    """

    provider: str
    model: str

    def send(
        self,
        abstract_code: str,
        task: str = "review",
        query: Optional[str] = None,
        language: str = "python",
    ) -> LLMResponse:
        """Send abstract code and return the model's answer."""
        ...


# ═══════════════════════════════════════════════════════════
# Retry policy
# ═══════════════════════════════════════════════════════════

# Substrings that mark a failure as worth retrying.  Matching on the text
# of the error rather than on vendor exception classes keeps this working
# when a provider SDK is not installed -- and all three SDKs put these
# words in the message.
_TRANSIENT_MARKERS = (
    'rate limit', 'ratelimit', 'too many requests', '429',
    'timeout', 'timed out', 'deadline',
    'connection', 'unavailable', 'overloaded', 'temporarily',
    '500', '502', '503', '504',
    'internal server error', 'bad gateway', 'service unavailable',
)


def is_transient(error: BaseException) -> bool:
    """
    Decide whether an error is worth another attempt.

    Retrying a malformed request or a bad API key spends quota to receive
    the identical error, so only load-shedding and transport failures
    qualify.
    """
    text = f"{type(error).__name__} {error}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


@dataclass
class RetryPolicy:
    """Exponential backoff shared by every provider."""

    max_attempts: int = 3
    initial_backoff: float = 1.0
    multiplier: float = 2.0
    max_backoff: float = 8.0
    # Injectable so tests exercise the retry path without sleeping.
    sleep: Callable[[float], None] = time.sleep

    def backoff_for(self, attempt: int) -> float:
        """Delay in seconds before *attempt* (1-based, so attempt 2 is the first retry)."""
        delay = self.initial_backoff * (self.multiplier ** max(0, attempt - 2))
        return min(delay, self.max_backoff)


DEFAULT_TIMEOUT = 60.0


# ═══════════════════════════════════════════════════════════
# Base client
# ═══════════════════════════════════════════════════════════

class BaseLLMClient:
    """
    Template implementation of :class:`LLMClient`.

    Subclasses implement :meth:`_generate` — one call to their SDK — and
    inherit prompt assembly, the retry loop, timing, error capture and
    token accounting. Everything that could drift between providers if
    each rewrote it lives here instead.
    """

    provider: str = "unknown"
    default_model: str = ""

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: Optional[RetryPolicy] = None,
    ):
        if not api_key:
            raise ValueError(f"{self.provider}: an API key is required")
        self.api_key = api_key
        self.model = model or self.default_model
        self.timeout = timeout
        self.retry = retry or RetryPolicy()

    # -- to implement -------------------------------------------------

    def _generate(self, prompt: str) -> Tuple[str, TokenUsage]:
        """Perform one request. Raise on failure; the base class retries."""
        raise NotImplementedError

    # -- shared -------------------------------------------------------

    def send(
        self,
        abstract_code: str,
        task: str = "review",
        query: Optional[str] = None,
        language: str = "python",
    ) -> LLMResponse:
        """
        Send abstract code (and optionally an abstracted free-form query).

        Never raises for a provider failure: the failure is reported in the
        returned :class:`LLMResponse`, because a CLI that tracebacks on a
        rate limit is worse than one that says "rate limited".
        """
        prompt = build_prompt(abstract_code, task=task, query=query, language=language)
        start = time.time()
        last_error: Optional[BaseException] = None
        attempt = 0

        for attempt in range(1, self.retry.max_attempts + 1):
            if attempt > 1:
                self.retry.sleep(self.retry.backoff_for(attempt))
            try:
                content, usage = self._generate(prompt)
                return LLMResponse(
                    content=content,
                    response_time=time.time() - start,
                    success=True,
                    provider=self.provider,
                    model=self.model,
                    usage=usage,
                    attempts=attempt,
                )
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                last_error = exc
                if not is_transient(exc):
                    break

        return LLMResponse(
            content="",
            response_time=time.time() - start,
            success=False,
            error=str(last_error),
            provider=self.provider,
            model=self.model,
            attempts=attempt,
        )
