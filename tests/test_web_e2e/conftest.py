"""
Real-browser E2E infrastructure for the web workbench.

``tests/test_web/`` drives the app through Flask's test client, which never
instantiates a DOM, never runs ``web/static/app.js``, and never renders a
CSP. It proves the *response bodies* carry no secret. It cannot prove the
page that a person actually looks at doesn't -- browser storage, the
rendered DOM, script execution, and real network requests only exist once
something serves the app over a socket and a browser fetches it.

This package boots the real Flask app in a background thread on a real
loopback socket, and drives it with Playwright. The app is wired to
:class:`FakeLLMClient` (imported from ``tests.test_web.conftest``, so the
credential-shaped fixtures used at the response-body layer are exactly the
ones asserted on here) -- no network call, no API key, and deterministic
replies to assert against.
"""

import threading

import pytest
from werkzeug.serving import make_server

from tests.test_web.conftest import (  # noqa: F401  (re-exported for test files)
    AWS_KEY_ID,
    CLEAN_SOURCE,
    DB_PASSWORD,
    FakeLLMClient,
    JS_SOURCE,
    SECRET_SOURCE,
    SECRETS,
    STRIPE_KEY,
)

CANARY = "CANARY_SECRET_FRONTEND_TEST_12345"

CANARY_SOURCE = f'''API_TOKEN = "{CANARY}"
retry_limit = 5


def send(amount):
    return amount + retry_limit
'''


class _ServerThread(threading.Thread):
    """A real HTTP server for the Flask app, on an OS-assigned loopback port."""

    def __init__(self, app):
        super().__init__(daemon=True)
        self._server = make_server("127.0.0.1", 0, app)
        self.port = self._server.server_port

    def run(self):
        self._server.serve_forever(poll_interval=0.05)

    def stop(self):
        self._server.shutdown()


@pytest.fixture
def live_server_factory():
    """
    Build a running instance of the app. Callable more than once per test
    for the tests that need two independently configured servers.

    Returns a callable ``(config=None, client=None) -> live_url``.
    """
    threads = []

    def _make(config=None, client=None):
        from web import create_app

        app = create_app({
            "TESTING": True,
            "SAVE_SESSIONS": True,
            "ALLOW_REVEAL": False,
            "LLM_CLIENT": FakeLLMClient() if client is None else client,
            **(config or {}),
        })
        thread = _ServerThread(app)
        thread.start()
        threads.append(thread)
        return f"http://127.0.0.1:{thread.port}"

    yield _make

    for thread in threads:
        thread.stop()
        thread.join(timeout=5)


@pytest.fixture
def live_url(live_server_factory):
    """The common case: one server, default fake provider, reveal off."""
    return live_server_factory()


@pytest.fixture
def fake_client():
    return FakeLLMClient()


@pytest.fixture(autouse=True)
def _reset_auth_rate_limits():
    """See tests/test_web/conftest.py's fixture of the same name."""
    from web.auth import reset_rate_limiters

    reset_rate_limiters()
    yield
    reset_rate_limiters()


@pytest.fixture
def console_errors(page):
    """
    Collect console 'error' messages and uncaught page exceptions for the
    duration of a test. A test asserts on this explicitly rather than the
    suite failing globally on any console noise, per Phase 21 -- a known
    harmless warning shouldn't fail the run, but a test that cares can check.
    """
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


@pytest.fixture
def failed_requests(page):
    """Requests that finished with a failure (network error, not HTTP status)."""
    failures = []
    page.on("requestfailed", lambda req: failures.append((req.url, req.failure)))
    return failures
