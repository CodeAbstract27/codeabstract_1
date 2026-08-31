"""
Phase 3 — page load, in a real browser.

Every page the app serves: does it render, are the controls present and in
the right initial state, does the CSP the app declares actually let the page
work (a CSP that blocks the app's own script would be a self-inflicted
outage that no Flask-test-client run would ever catch, since that client
never enforces headers).
"""

import pytest


def test_workbench_loads(page, live_url, console_errors):
    page.goto(live_url + "/")

    assert page.title() == "Workbench — CodeAbstract"
    # The sample source is pre-filled and the pipeline is fully wired --
    # this only holds if app.js executed under the page's own CSP.
    assert "STRIPE_API_KEY" in page.input_value("#source")
    assert page.input_value("#filename") == "payments.py"
    assert page.is_visible("#btn-abstract")
    assert page.is_visible("#btn-review")
    assert not page.is_disabled("#btn-abstract")
    assert not page.is_disabled("#btn-review")

    # Nothing has run yet: output stays hidden until a result exists.
    assert page.is_hidden("#summary")
    assert page.is_hidden("#code-panel")
    assert page.is_hidden("#output-panel")

    assert console_errors == []


def test_reveal_checkbox_absent_without_allow_reveal(page, live_url):
    """ALLOW_REVEAL is off by default; the control must not even render."""
    page.goto(live_url + "/")
    assert page.locator("#reveal").count() == 0


def test_reveal_checkbox_present_when_allowed(page, live_server_factory):
    live_url = live_server_factory(config={"ALLOW_REVEAL": True})
    page.goto(live_url + "/")
    assert page.locator("#reveal").count() == 1
    assert not page.is_checked("#reveal")


def test_sessions_page_loads_empty(page, live_server_factory):
    """
    Uses its own live_server_factory() call rather than the shared live_url
    fixture: every server in this suite points at the same process-wide
    CODEABSTRACT_HOME database (set once by tests/conftest.py for the whole
    pytest run), so "no sessions yet" is only true before *any* test in the
    run has created one. Sharing a fresh Flask app doesn't help -- the
    database underneath it is still the same file -- so this asserts on
    literal emptiness only when nothing has run yet, which held when this
    test happened to run first but broke (order-dependent flake) once it
    ran after other tests in the same session. The page's actual behavior
    here doesn't depend on session ordering, so it never needed the shared
    fixture: skip cleanly if some other test already seeded a session.
    """
    from web.service import recent_sessions

    if recent_sessions(1):
        pytest.skip("a session already exists from an earlier test in this run")

    live_url = live_server_factory()
    page.goto(live_url + "/sessions")
    assert page.title() == "Sessions — CodeAbstract"
    assert page.get_by_text("No sessions yet.").is_visible()
    assert page.is_hidden("#translate-output")


def test_sessions_page_lists_prior_session(page, live_url):
    """A session created via the workbench shows up on /sessions afterward."""
    page.goto(live_url + "/")
    page.click("#btn-abstract")
    page.wait_for_selector("#summary:not([hidden])")

    page.goto(live_url + "/sessions")
    rows = page.locator("#session-rows tr")
    assert rows.count() >= 1
    assert rows.first.locator(".use-session").is_visible()
    assert rows.first.locator(".delete-session").is_visible()


def test_health_endpoint(page, live_url):
    response = page.request.get(live_url + "/health")
    assert response.ok
    data = response.json()
    assert data["status"] == "ok"
    assert "python" in data["languages"]


def test_404_page_renders_for_browser_navigation(page, live_url):
    response = page.goto(live_url + "/no-such-page")
    assert response.status == 404
    assert page.get_by_text("Not found.").is_visible()
    assert page.get_by_role("link", name="Back to the workbench").is_visible()


def test_security_headers_present_on_every_response(page, live_url):
    """
    The CSP is what makes an escaping mistake elsewhere survivable (see
    web/app.py's module docstring) -- so its actual presence on the wire,
    not just the config that intends to add it, is worth asserting.
    """
    response = page.goto(live_url + "/")
    headers = response.headers
    assert "script-src 'self'" in headers["content-security-policy"]
    assert "object-src 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"


def test_static_assets_load(page, live_url):
    responses = []
    page.on("response", lambda r: responses.append(r))
    page.goto(live_url + "/")
    page.wait_for_load_state("networkidle")

    css = [r for r in responses if r.url.endswith("app.css")]
    js = [r for r in responses if r.url.endswith("app.js")]
    assert css and css[0].ok
    assert js and js[0].ok
