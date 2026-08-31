"""
Tests for web/auth.py and the account-scoping this added to web/service.py
and storage/session_manager.py.

Uses the same ``app``/``client``/``fake_client`` fixtures as the rest of
``tests/test_web`` (see conftest.py) — a real Flask app over the shared,
CODEABSTRACT_HOME-redirected session database, so a unique email per test
(via ``uuid4``) avoids collisions with accounts other tests in this run
have already created.
"""

import uuid

import pytest


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def _signup(client, email, password="a-strong-password"):
    return client.post('/api/auth/signup', json={'email': email, 'password': password})


def _login(client, email, password="a-strong-password"):
    return client.post('/api/auth/login', json={'email': email, 'password': password})


class TestSignup:
    def test_creates_account_and_signs_in(self, client):
        email = _email()
        response = _signup(client, email)
        assert response.status_code == 200
        assert response.get_json()['redirect'] == '/dashboard'

        # The session cookie now identifies this account.
        dashboard = client.get('/dashboard')
        assert dashboard.status_code == 200

    def test_rejects_short_password(self, client):
        response = _signup(client, _email(), password="short")
        assert response.status_code == 400
        assert 'error' in response.get_json()

    def test_rejects_invalid_email(self, client):
        response = _signup(client, "not-an-email")
        assert response.status_code == 400

    def test_rejects_duplicate_email(self, client):
        email = _email()
        assert _signup(client, email).status_code == 200
        second = _signup(client, email)
        assert second.status_code == 400
        assert 'already exists' in second.get_json()['error']

    def test_requires_json_content_type(self, client):
        response = client.post(
            '/api/auth/signup', data='email=a@b.com&password=whatever',
        )
        assert response.status_code == 415


class TestLogin:
    def test_correct_credentials_succeed(self, client):
        email = _email()
        _signup(client, email, password="correct-horse-battery")
        client.post('/logout')
        response = _login(client, email, password="correct-horse-battery")
        assert response.status_code == 200
        assert client.get('/dashboard').status_code == 200

    def test_wrong_password_fails(self, client):
        email = _email()
        _signup(client, email, password="correct-horse-battery")
        client.post('/logout')
        response = _login(client, email, password="wrong-password")
        assert response.status_code == 401

    def test_unknown_email_fails(self, client):
        response = _login(client, _email(), password="whatever12345")
        assert response.status_code == 401

    def test_logout_clears_session(self, client):
        _signup(client, _email())
        client.post('/logout')
        assert client.get('/dashboard').status_code == 302


class TestLoginGate:
    def test_dashboard_redirects_when_signed_out(self, client):
        assert client.get('/dashboard').status_code == 302

    def test_insights_redirects_when_signed_out(self, client):
        assert client.get('/insights').status_code == 302

    def test_dashboard_api_401s_when_signed_out(self, client):
        response = client.get('/api/dashboard')
        assert response.status_code == 401

    def test_workbench_and_sessions_stay_open_when_signed_out(self, client):
        # These predate accounts and must keep working anonymously.
        assert client.get('/').status_code == 200
        assert client.get('/sessions').status_code == 200
        assert client.get('/api/sessions').status_code == 200


def _owns(client, session_id) -> bool:
    """True if session_id shows up in this client's own session list."""
    ids = [row['session_id'] for row in client.get('/api/sessions').get_json()['sessions']]
    return session_id in ids


class TestAccountIsolation:
    """
    Regression test for a real bug found while hand-testing this feature:
    an anonymous ``user_id=None`` was originally treated as "no filter" in
    storage.session_manager, so a signed-out caller (or a different
    account) could read another account's session list and session detail
    through the exact same API a signed-in owner uses.

    Each test in this file gets its own private ``~/.codeabstract`` (see
    the ``app`` fixture in tests/test_web/conftest.py), so these
    assertions check for the *specific* session's absence rather than an
    empty list mostly out of habit — it is the more precise check either
    way, and it is what made this test's original, empty-list version
    flaky before that per-test isolation existed.
    """

    def test_one_account_cannot_see_another_accounts_session(self, app, fake_client):
        owner = app.test_client()
        _signup(owner, _email())
        abstracted = owner.post('/api/abstract', json={
            'code': 'API_KEY = "sk_live_abc123def456ghi789"\ndef f(x):\n    return x + 1\n',
            'filename': 'a.py',
        })
        assert abstracted.status_code == 200
        session_id = abstracted.get_json()['session_id']

        # A different signed-in account must not see it.
        other = app.test_client()
        _signup(other, _email())
        assert not _owns(other, session_id)
        assert other.get(f'/api/sessions/{session_id}').status_code == 404

        # Nor may a signed-out visitor.
        anon = app.test_client()
        assert not _owns(anon, session_id)
        assert anon.get(f'/api/sessions/{session_id}').status_code == 404

        # The owner still can.
        assert _owns(owner, session_id)
        assert owner.get(f'/api/sessions/{session_id}').status_code == 200

    def test_anonymous_sessions_are_not_owned_by_the_next_signed_in_visitor(self, app):
        anon = app.test_client()
        abstracted = anon.post('/api/abstract', json={
            'code': 'def f(x):\n    return x + 1\n',
            'filename': 'clean.py',
        })
        session_id = abstracted.get_json()['session_id']

        signed_in = app.test_client()
        _signup(signed_in, _email())
        assert not _owns(signed_in, session_id)
        assert signed_in.get(f'/api/sessions/{session_id}').status_code == 404


class TestRateLimiting:
    def test_login_locks_out_after_repeated_failures(self, client):
        email = _email()
        _signup(client, email, password="correct-horse-battery")
        client.post('/logout')

        for _ in range(5):
            response = _login(client, email, password="wrong-password")
            assert response.status_code == 401

        locked = _login(client, email, password="wrong-password")
        assert locked.status_code == 429

        # The correct password doesn't bypass an active lockout.
        still_locked = _login(client, email, password="correct-horse-battery")
        assert still_locked.status_code == 429

    def test_successful_login_clears_the_counter(self, client):
        email = _email()
        _signup(client, email, password="correct-horse-battery")
        client.post('/logout')

        for _ in range(3):
            assert _login(client, email, password="wrong-password").status_code == 401

        assert _login(client, email, password="correct-horse-battery").status_code == 200

        client.post('/logout')
        # Fresh failures after a successful login should not carry over
        # the count from before it.
        for _ in range(3):
            assert _login(client, email, password="wrong-password").status_code == 401
        assert _login(client, email, password="correct-horse-battery").status_code == 200

    def test_lockout_is_scoped_to_this_account_not_every_account(self, client):
        target = _email()
        _signup(client, target, password="correct-horse-battery")
        client.post('/logout')

        for _ in range(5):
            _login(client, target, password="wrong-password")
        assert _login(client, target, password="wrong-password").status_code == 429

        other_email = _email()
        _signup(client, other_email, password="another-strong-pass")
        client.post('/logout')
        # A different account, same client address, is unaffected.
        assert _login(client, other_email, password="another-strong-pass").status_code == 200

    def test_signup_is_rate_limited_per_address(self, client):
        from web.auth import _signup_limiter

        for _ in range(10):
            _signup_limiter.record('127.0.0.1')

        response = _signup(client, _email())
        assert response.status_code == 429


class TestNoInlineStyles:
    """
    Regression guard for a real bug: the Dashboard and Insights bar charts
    used to write ``style="height: N%"`` directly, which the CSP's
    ``style-src 'self'`` (web/app.py) silently blocks in a real browser --
    every bar rendered at 0% height, and nothing in the test suite caught
    it because nothing asserted on bar geometry or CSP console errors.
    Found only by loading the page in an actual browser and reading its
    console. web/app.py's ``pct_class`` Jinja global (bucketed CSS
    classes) replaced the inline styles; this pins that invariant so a
    future chart doesn't reintroduce the same silent breakage.
    """

    def test_dashboard_renders_no_inline_style_attributes(self, client):
        _signup(client, _email())
        client.post('/api/abstract', json={
            'code': 'API_KEY = "sk_live_abc123def456ghi789"\ndef f(x):\n    return x + 1\n',
            'filename': 'a.py',
        })
        html = client.get('/dashboard').data.decode()
        assert 'style=' not in html

    def test_insights_renders_no_inline_style_attributes(self, client):
        _signup(client, _email())
        html = client.get('/insights').data.decode()
        assert 'style=' not in html


class TestInsightsAndDashboardData:
    def test_dashboard_reflects_only_this_accounts_activity(self, client):
        _signup(client, _email())
        before = client.get('/api/dashboard').get_json()['total_sessions']

        client.post('/api/abstract', json={
            'code': 'API_KEY = "sk_live_abc123def456ghi789"\ndef f(x):\n    return x + 1\n',
            'filename': 'a.py',
        })

        after = client.get('/api/dashboard').get_json()
        assert after['total_sessions'] == before + 1
        assert after['total_secrets_found'] >= 1
        assert any(row['sessions'] for row in after['activity'])

    def test_insights_audit_endpoint_reports_chain_status(self, client):
        _signup(client, _email())
        data = client.get('/api/audit').get_json()
        assert 'chain_ok' in data
        assert 'entries' in data

    def test_audit_entries_are_scoped_to_the_account_that_made_them(self, app):
        """
        The chain-integrity check covers the whole log (it must, to detect
        tampering anywhere in it) but the entry list must not leak one
        account's abstractions and requests into another's view.
        """
        owner = app.test_client()
        _signup(owner, _email())
        owner.post('/api/abstract', json={
            'code': 'API_KEY = "sk_live_abc123def456ghi789"\ndef f(x):\n    return x + 1\n',
            'filename': 'owner.py',
        })
        owner_entries = owner.get('/api/audit').get_json()['entries']
        assert any(e.get('source_file', '').endswith('owner.py') for e in owner_entries)

        other = app.test_client()
        _signup(other, _email())
        other_entries = other.get('/api/audit').get_json()['entries']
        assert not any(e.get('source_file', '').endswith('owner.py') for e in other_entries)

        # The chain check itself still runs over every entry on the
        # machine, owner's and other's alike.
        assert owner.get('/api/audit').get_json()['chain_ok'] is True

    def test_benchmarks_endpoint_reports_unavailable_or_a_summary(self, client):
        _signup(client, _email())
        data = client.get('/api/benchmarks').get_json()
        assert 'available' in data
        if data['available']:
            assert 'classification' in data
