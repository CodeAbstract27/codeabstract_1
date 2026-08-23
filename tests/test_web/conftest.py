"""
Fixtures for the web interface tests.

Phase 5. Two things are shared by everything here.

**A stand-in provider.** ``FakeLLMClient`` satisfies
:class:`llm.base.LLMClient` and is injected through the app's ``LLM_CLIENT``
config key, which is the seam :func:`web.service.run_review` leaves for
exactly this. That means the review pipeline is tested end to end — abstract,
send, reconstruct, audit — with no API key, no network, and no
monkeypatching of internals that could drift from the real call.

It also records what it was sent, which is how the privacy tests can assert
on the *payload* rather than on the response. What left the machine is the
thing the project's guarantee is about, and it is only observable here.

**Source with real credential shapes.** ``SECRET_SOURCE`` uses formats the
detector recognises by vendor prefix — a Stripe key, an AWS key ID, a
connection string — because a test that redacts ``"my-password"`` proves
only that the word ``password`` is in a regex.
"""

import pytest

from llm.base import LLMResponse, TokenUsage

# Credential-shaped values that must never appear in anything derived from
# the source. Assembled at import so the strings sit in one place and the
# assertions cannot drift from the fixture.
STRIPE_KEY = "sk_live_51H8xY2eZvKYlo2CkQmZ9pXrT"
AWS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
DB_PASSWORD = "hunter2-correct-horse-battery"

SECRETS = (STRIPE_KEY, AWS_KEY_ID, DB_PASSWORD)

SECRET_SOURCE = f'''import os

STRIPE_API_KEY = "{STRIPE_KEY}"
AWS_ACCESS_KEY_ID = "{AWS_KEY_ID}"
DATABASE_URL = "postgres://admin:{DB_PASSWORD}@db.internal/orders"

commission_rate = 0.029
retry_limit = 5


def calculate_commission(amount):
    """Commission on a settled transaction."""
    fee = amount * commission_rate
    return round(fee, 2)


def charge_customer(customer_id, amount):
    headers = {{"Authorization": f"Bearer {{STRIPE_API_KEY}}"}}
    total = amount + calculate_commission(amount)
    return {{"customer": customer_id, "total": total, "headers": headers}}


def retry_all(queue):
    # The single-character name is deliberate: `abstract_short_names` is the
    # only setting that separates `critical` from `high`, so without one in
    # the fixture the two levels are identical and the test that asserts
    # four distinct outputs would be asserting nothing.
    n = 0
    for item in queue:
        n = n + retry_limit
    return n
'''

CLEAN_SOURCE = '''def total_price(items):
    """Sum a basket."""
    running_total = 0
    for entry in items:
        running_total = running_total + entry
    return running_total
'''

JS_SOURCE = '''const apiToken = "sk_live_51H8xY2eZvKYlo2CkQmZ9pXrT";

function settleInvoice(invoiceId, amount) {
  const commissionRate = 0.029;
  return amount + amount * commissionRate;
}
'''


class FakeLLMClient:
    """
    A provider that answers without a network, and remembers what it saw.

    The reply is built from the tokens actually present in the abstract
    code, so the reconstruction assertions hold whatever tokens a given
    privacy level happens to produce. A hard-coded ``VAR_0`` would pass
    while testing nothing on a run that never allocated one.
    """

    def __init__(
        self,
        provider: str = 'fake',
        model: str = 'fake-1',
        success: bool = True,
        error: str = None,
        reply: str = None,
    ):
        self.provider = provider
        self.model = model
        self.success = success
        self.error = error
        self.reply = reply
        self.calls = []

    def send(self, abstract_code, task='review', query=None, language='python'):
        from llm.base import build_prompt

        prompt = build_prompt(abstract_code, task=task, query=query, language=language)
        self.calls.append({
            'abstract_code': abstract_code,
            'task': task,
            'query': query,
            'language': language,
            'prompt': prompt,
        })

        return LLMResponse(
            content=self.reply if self.reply is not None else self._compose(abstract_code),
            response_time=0.01,
            success=self.success,
            error=self.error,
            provider=self.provider,
            model=self.model,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=40, reported=True),
            attempts=1,
        )

    @staticmethod
    def _compose(abstract_code: str) -> str:
        """An answer that cites tokens and a line, as a real one would."""
        from web.service import TOKEN_PATTERN

        tokens = []
        for token in TOKEN_PATTERN.findall(abstract_code):
            if token not in tokens:
                tokens.append(token)

        cited = tokens[:3] or ['VAR_0']
        return (
            f"Line 3: {cited[0]} is recomputed on every call.\n"
            f"Consider caching {cited[-1]} instead.\n"
            "Also note VAR_9999 appears unused."
        )

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]['prompt'] if self.calls else ''


@pytest.fixture
def fake_client():
    """A provider stand-in with default success behaviour."""
    return FakeLLMClient()


@pytest.fixture
def app(fake_client):
    """The application, wired to the fake provider."""
    from web import create_app

    return create_app({
        'TESTING': True,
        'SAVE_SESSIONS': True,
        'ALLOW_REVEAL': False,
        'LLM_CLIENT': fake_client,
    })


@pytest.fixture
def client(app):
    """A test client for the configured app."""
    return app.test_client()


@pytest.fixture
def secret_source():
    return SECRET_SOURCE


@pytest.fixture
def clean_source():
    return CLEAN_SOURCE
