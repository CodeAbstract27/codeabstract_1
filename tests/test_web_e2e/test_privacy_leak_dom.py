"""
Phase 10 — privacy and secret-leak testing, at the DOM, not the JSON.

``tests/test_web/test_web_privacy.py`` already proves no credential value
survives into a JSON response body. That is necessary but not sufficient:
the browser is a second place a value can appear that a JSON walk never
sees -- a ``title`` attribute rendered from a field the JSON-walker
skipped, a value a script wrote into storage, a value present in a request
the JSON assertions never inspected because it was a *request*, not a
response.

Every test here works from the rendered page: ``page.content()`` (full
serialized DOM, hidden nodes included), storage, and the network traffic
actually sent to the fake provider. A canary that appears nowhere but the
page's own echo of the user's paste is the one specific claim this suite
makes; anywhere else it is a finding.
"""

import json

import pytest

from tests.test_web_e2e.conftest import (
    AWS_KEY_ID,
    CANARY,
    CANARY_SOURCE,
    DB_PASSWORD,
    SECRET_SOURCE,
    SECRETS,
    STRIPE_KEY,
)


def _run_abstract(page, live_url, code, filename="payments.py"):
    page.goto(live_url + "/")
    page.fill("#source", code)
    page.fill("#filename", filename)
    page.click("#btn-abstract")
    page.wait_for_selector("#summary:not([hidden])")


def _run_review(page, live_url, code, filename="payments.py", query=""):
    page.goto(live_url + "/")
    page.fill("#source", code)
    page.fill("#filename", filename)
    if query:
        page.fill("#query", query)
    page.click("#btn-review")
    page.wait_for_selector("#summary:not([hidden])")


class TestCanaryInAbstractedDOM:
    """A secret pasted in must not resurface anywhere except the original pane."""

    def test_canary_absent_from_abstract_pane(self, page, live_url):
        _run_abstract(page, live_url, CANARY_SOURCE)
        abstract_html = page.locator("#pane-abstract").inner_html()
        assert CANARY not in abstract_html

    def test_canary_absent_from_vault_pane(self, page, live_url):
        _run_abstract(page, live_url, CANARY_SOURCE)
        vault_html = page.locator("#vault-table").inner_html()
        assert CANARY not in vault_html

    def test_canary_absent_from_report_pane(self, page, live_url):
        _run_abstract(page, live_url, CANARY_SOURCE)
        page.click('[data-tab="report"]')
        report_html = page.locator("#tab-report").inner_html()
        assert CANARY not in report_html

    def test_canary_absent_from_tooltips_and_all_attributes(self, page, live_url):
        """
        A masked value could still leak through an attribute a naive text
        check would miss -- ``title``, ``data-*``, anything. ``page.content()``
        serializes the whole DOM including attributes, so this is the
        broadest single check available -- outside of ``#pane-original``,
        which is the one documented, deliberately-tested exception (see
        ``test_original_pane_is_the_one_allowed_exception`` below): it
        echoes the user's own paste, and a bare ``page.content()`` check
        would fail on that expected occurrence rather than a real leak.
        """
        _run_abstract(page, live_url, CANARY_SOURCE)
        content_without_original_pane = page.evaluate(
            """() => {
                const clone = document.body.cloneNode(true);
                const original = clone.querySelector('#pane-original');
                if (original) { original.remove(); }
                return clone.outerHTML;
            }"""
        )
        assert CANARY not in content_without_original_pane

    def test_canary_absent_from_full_page_text(self, page, live_url):
        """
        Uses textContent rather than innerText: the check runs against a
        detached clone (see the docstring above), and innerText's value
        depends on live layout, which a detached node doesn't have and
        would make this assertion pass vacuously regardless of content.
        """
        _run_abstract(page, live_url, CANARY_SOURCE)
        text_without_original_pane = page.evaluate(
            """() => {
                const clone = document.body.cloneNode(true);
                const original = clone.querySelector('#pane-original');
                if (original) { original.remove(); }
                return clone.textContent;
            }"""
        )
        assert CANARY not in text_without_original_pane

    def test_original_pane_is_the_one_allowed_exception(self, page, live_url):
        """
        The one place the canary is *supposed* to appear: the user's own
        paste, echoed back to the tab it came from. If it disappeared from
        here the side-by-side view would be lying about what was submitted.
        """
        _run_abstract(page, live_url, CANARY_SOURCE)
        original_html = page.locator("#pane-original").inner_html()
        assert CANARY in original_html


class TestRealCredentialShapesInDOM:
    """The same claim, restated against vendor-shaped secrets, not a synthetic canary."""

    @pytest.mark.parametrize("secret", SECRETS)
    def test_credential_masked_everywhere_except_original_pane(self, page, live_url, secret):
        _run_abstract(page, live_url, SECRET_SOURCE)

        assert secret in page.locator("#pane-original").inner_html()

        for pane_id in ("#pane-abstract", "#vault-table", "#report-table",
                        "#report-summary", "#checklist", "#stat-strip"):
            assert secret not in page.locator(pane_id).inner_html(), (
                f"{secret[:8]}... leaked into {pane_id}"
            )

    def test_credential_masked_in_llm_review_panes(self, page, live_url):
        """
        The raw-response and mapped-feedback panes render text that passed
        through an external "provider" (the fake client here) and back --
        the two panes furthest from the original source, and the ones a
        masking regression would be easiest to miss in.
        """
        _run_review(page, live_url, SECRET_SOURCE)
        page.click('[data-tab="raw"]')
        page.click('[data-tab="mapped"]')

        raw = page.locator("#raw-response").inner_html()
        mapped = page.locator("#mapped-feedback").inner_html()
        for secret in SECRETS:
            assert secret not in raw
            assert secret not in mapped

    def test_the_request_to_the_server_legitimately_carries_the_raw_source(
        self, page, live_url,
    ):
        """
        Not a leak: this is the one hop where a credential is *supposed* to
        travel in the clear. The browser cannot abstract the source itself
        -- that's the server's job -- so /api/review's POST body, including
        the free-form question, necessarily carries what the user typed.
        The boundary this project actually promises to hold is one hop
        further out: no secret reaches the *provider* payload, which is
        what fake_client.last_prompt asserts in
        tests/test_web/test_web_privacy.py, and what
        TestRealCredentialShapesInDOM above re-asserts from the panes a
        browser renders afterward. Stated here so a reader of this file
        doesn't go looking for a browser-side redaction step that was never
        part of the design.
        """
        request_bodies = []

        def _capture(request):
            if request.method == "POST" and request.url.endswith("/api/review"):
                request_bodies.append(request.post_data or "")

        page.on("request", _capture)
        _run_review(page, live_url, SECRET_SOURCE,
                    query=f"Is {STRIPE_KEY} safe to log?")

        assert request_bodies, "no /api/review request was captured"
        body = json.loads(request_bodies[0])
        assert STRIPE_KEY in body["code"]
        assert STRIPE_KEY in body["query"]


class TestBrowserStorageAndCookies:
    """Phase 13 folded in here: same canary, same workflow, storage instead of DOM."""

    def test_no_secret_in_local_storage(self, page, live_url):
        _run_review(page, live_url, SECRET_SOURCE)
        dump = page.evaluate(
            "() => JSON.stringify(Object.entries(localStorage))"
        )
        for secret in SECRETS:
            assert secret not in dump

    def test_no_secret_in_session_storage(self, page, live_url):
        _run_review(page, live_url, SECRET_SOURCE)
        dump = page.evaluate(
            "() => JSON.stringify(Object.entries(sessionStorage))"
        )
        for secret in SECRETS:
            assert secret not in dump

    def test_no_cookies_are_set_at_all(self, page, live_url):
        """
        No auth model, no session cookie, nothing that would carry a value
        between requests outside the vault the server already owns.
        """
        page.goto(live_url + "/")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert page.context.cookies() == []

    def test_session_storage_key_referenced_in_app_js_is_never_actually_set(
        self, page, live_url,
    ):
        """
        app.js reads ``sessionStorage['codeabstract.session']`` on load and
        has a message ready for it ("Session ... — paste its response on
        the Sessions page..."), attributed to "a session chosen on the
        Sessions page". Nothing in sessions.js's ``useSession`` (which only
        fills the translate field in place) or anywhere else ever calls
        ``sessionStorage.setItem`` for that key. This is not a privacy leak
        -- it's the opposite, dead code that can never run -- but it means
        the workbench's "resume a session" messaging is unreachable, which
        is worth flagging as a real (non-security) frontend defect.
        """
        page.goto(live_url + "/sessions")
        page.evaluate("() => sessionStorage.clear()")
        rows = page.locator("#session-rows tr")
        if rows.count() == 0:
            pytest.skip("no session to select")
        rows.first.locator(".use-session").click()

        # Confirm the documented trigger path really doesn't set the key.
        value = page.evaluate(
            "() => sessionStorage.getItem('codeabstract.session')"
        )
        assert value is None
