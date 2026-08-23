"""
LLM Provider Registry and Factory

Phase 4 — this is the piece the audit named directly: the old factory took
an ``api_key`` and returned a Gemini client, while the packaging advertised
three providers. ``create_client(provider='openai')`` was not merely
unimplemented, it was silently ignored.

The registry below is the single place that knows a provider exists. A
provider is described by its client class, its default model, and the
environment variables that carry its key; adding a fourth is one entry plus
one :class:`llm.base.BaseLLMClient` subclass.

Resolution order for the provider, most explicit first:

1. the ``--provider`` argument,
2. ``CODEABSTRACT_PROVIDER`` in the environment,
3. ``default_provider`` in ``~/.codeabstract/config.json``,
4. the only provider that has both a key and its package installed,
5. otherwise an error naming what is missing.

Step 4 exists so that a user with exactly one key configured never has to
say which provider they mean; step 5 refuses to guess when several are
possible, because silently picking one would bill an account the user did
not choose to bill.
"""

import os
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from typing import Dict, List, Optional, Tuple

from llm.base import (  # noqa: F401 - re-exported as the public interface
    DEFAULT_TIMEOUT,
    LLMClient,
    LLMResponse,
    RetryPolicy,
    TASK_PROMPTS,
    TokenUsage,
    build_prompt,
)


@dataclass(frozen=True)
class ProviderSpec:
    """Everything the factory needs to know about one provider."""

    name: str
    module: str
    class_name: str
    default_model: str
    env_vars: Tuple[str, ...]
    package: str
    extra: str

    def is_installed(self) -> bool:
        """True if the vendor SDK is importable."""
        return find_spec(self.package.split('.')[0]) is not None


PROVIDERS: Dict[str, ProviderSpec] = {
    'gemini': ProviderSpec(
        name='gemini',
        module='llm.gemini_client',
        class_name='GeminiClient',
        default_model='gemini-2.5-flash',
        env_vars=('GEMINI_API_KEY', 'GOOGLE_API_KEY'),
        package='google.generativeai',
        extra='gemini',
    ),
    'openai': ProviderSpec(
        name='openai',
        module='llm.openai_client',
        class_name='OpenAIClient',
        default_model='gpt-4o',
        env_vars=('OPENAI_API_KEY',),
        package='openai',
        extra='openai',
    ),
    'anthropic': ProviderSpec(
        name='anthropic',
        module='llm.anthropic_client',
        class_name='AnthropicClient',
        default_model='claude-sonnet-5',
        env_vars=('ANTHROPIC_API_KEY',),
        package='anthropic',
        extra='anthropic',
    ),
}

PROVIDER_NAMES: Tuple[str, ...] = tuple(PROVIDERS)

# Before Phase 4, ``create_client(api_key=key)`` meant Gemini -- there was
# nothing else it could mean.  An explicit key with no provider named still
# means that, so pre-Phase-4 callers keep working.
LEGACY_DEFAULT_PROVIDER = 'gemini'


class ProviderError(RuntimeError):
    """Raised when a provider cannot be selected or constructed."""


# ═══════════════════════════════════════════════════════════
# Key and provider resolution
# ═══════════════════════════════════════════════════════════

def get_spec(provider: str) -> ProviderSpec:
    """Look up a provider, with a message that lists the alternatives."""
    key = (provider or '').strip().lower()
    if key not in PROVIDERS:
        raise ProviderError(
            f"Unknown provider '{provider}'. "
            f"Available: {', '.join(PROVIDER_NAMES)}"
        )
    return PROVIDERS[key]


def resolve_api_key(provider: str) -> Optional[str]:
    """
    Find a provider's API key.

    Environment first, then ``~/.codeabstract/config.json``. A key exported
    for this shell should win over one saved months ago.
    """
    spec = get_spec(provider)

    for var in spec.env_vars:
        value = os.environ.get(var)
        if value:
            return value

    from config.settings import get_api_key
    return get_api_key(spec.name)


def resolve_model(provider: str, model: Optional[str] = None) -> str:
    """Pick the model: explicit, then configured, then the provider default."""
    spec = get_spec(provider)
    if model:
        return model

    from config.settings import get_config
    configured = get_config().get(f"{spec.name}_model")
    return configured or spec.default_model


def provider_status() -> List[Dict]:
    """
    Report every provider's readiness, for ``codeabstract providers list``.

    Reports installation and key presence separately: "no key" and "no
    package" need different fixes, and collapsing them into "unavailable"
    sends the user looking in the wrong place.
    """
    from config.settings import get_config

    configured_default = get_config().get('default_provider')
    return [
        {
            'provider': spec.name,
            'installed': spec.is_installed(),
            'has_key': bool(resolve_api_key(spec.name)),
            'model': resolve_model(spec.name),
            'env_vars': list(spec.env_vars),
            'extra': spec.extra,
            'is_default': spec.name == configured_default,
        }
        for spec in PROVIDERS.values()
    ]


def available_providers() -> List[str]:
    """Providers that are both installed and hold a key."""
    return [
        status['provider']
        for status in provider_status()
        if status['installed'] and status['has_key']
    ]


def resolve_provider(provider: Optional[str] = None) -> str:
    """
    Decide which provider to use. See the module docstring for the order.

    Raises:
        ProviderError: If nothing is usable, or if several are and no
            preference was expressed.
    """
    if provider:
        return get_spec(provider).name

    from_env = os.environ.get('CODEABSTRACT_PROVIDER')
    if from_env:
        return get_spec(from_env).name

    from config.settings import get_config
    configured = get_config().get('default_provider')
    if configured:
        return get_spec(configured).name

    usable = available_providers()
    if len(usable) == 1:
        return usable[0]
    if not usable:
        raise ProviderError(
            "No LLM provider is ready. Install one and set its key, e.g.\n"
            "  pip install 'codeabstract[gemini]' && export GEMINI_API_KEY=…\n"
            f"Supported providers: {', '.join(PROVIDER_NAMES)}"
        )
    raise ProviderError(
        f"Several providers are ready ({', '.join(usable)}). "
        "Choose one with --provider, or set a default:\n"
        "  codeabstract config set default_provider <name>"
    )


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════

def create_client(
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    retry: Optional[RetryPolicy] = None,
) -> LLMClient:
    """
    Build a client for the selected provider.

    Args:
        api_key: Explicit key. Resolved from environment or config if omitted.
        provider: ``gemini`` | ``openai`` | ``anthropic``. Resolved per the
            module docstring if omitted.
        model: Model identifier; the provider's default if omitted.
        timeout: Per-request timeout in seconds.
        retry: Retry policy; :class:`llm.base.RetryPolicy` defaults if omitted.

    Returns:
        A client satisfying :class:`llm.base.LLMClient`.

    Raises:
        ProviderError: Unknown provider, missing package, or missing key.

    Note:
        The pre-Phase-4 call ``create_client(api_key=key)`` still works: an
        explicit key with no provider named resolves to
        :data:`LEGACY_DEFAULT_PROVIDER`, which is what that call meant when
        Gemini was the only implementation.
    """
    if provider is None and api_key:
        try:
            name = resolve_provider(None)
        except ProviderError:
            name = LEGACY_DEFAULT_PROVIDER
    else:
        name = resolve_provider(provider)

    spec = get_spec(name)

    if not spec.is_installed():
        raise ProviderError(
            f"Provider '{name}' needs the '{spec.package}' package: "
            f"pip install 'codeabstract[{spec.extra}]'"
        )

    key = api_key or resolve_api_key(name)
    if not key:
        raise ProviderError(
            f"No API key for '{name}'. Set {' or '.join(spec.env_vars)}, "
            f"put it in a .env file, or run:\n"
            f"  codeabstract config set {name}_api_key <key>"
        )

    client_class = getattr(import_module(spec.module), spec.class_name)
    return client_class(
        api_key=key,
        model=resolve_model(name, model),
        timeout=timeout,
        retry=retry,
    )
