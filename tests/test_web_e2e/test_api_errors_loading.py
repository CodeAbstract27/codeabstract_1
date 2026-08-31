"""
Phases 8 and 9 — API response handling and asynchronous/loading state.

Route interception is used deliberately here, not the real backend: the
point of this file is to isolate frontend error handling from backend
behavior, which is exactly what lets it cover status codes (401, 403, 429)
the real service never actually returns. The one test that talks to the
real backend (``TestStaleResponseOrdering``) does so because the thing
under test -- whether an out-of-order response can clobber a newer one --
is a property of ``app.js`` reading real, different bodies, not of a
particular status code.
"""

import json
import time

import pytest
from playwright.sync_api import expect

from tests.test_web_e2e.conftest import CLEAN_SOURCE


def _mock_json(route, status, error="Something went wrong."):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps({"error": error}),
    )


class TestHttpErrorStatuses:
    """Every status the frontend has to be able to survive seeing."""

    @pytest.mark.parametrize("status,message", [
        (400, "Bad request: missing field."),
        (401, "Unauthorized."),
        (403, "Forbidden."),
        (404, "Not found."),
        (422, "Unprocessable: invalid privacy level."),
        (429, "Too many requests. Slow down."),
        (500, "Internal error — see the server log."),
        (502, "provider error after 3 attempt(s): connection reset"),
        (503, "No provider is configured."),
    ])
    def test_status_surfaces_the_servers_message_and_recovers_controls(
        self, page, live_url, status, message,
    ):
        page.route(
            "**/api/abstract",
            lambda route: _mock_json(route, status, message),
        )
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")

        page.wait_for_selector("#status.error")
        assert message in page.locator("#status").inner_text()
        assert page.is_hidden("#summary")
        assert not page.is_disabled("#btn-abstract")
        assert not page.is_disabled("#btn-review")

    def test_non_json_response_body_gets_a_generic_message_not_a_crash(
        self, page, live_url,
    ):
        page.route(
            "**/api/abstract",
            lambda route: route.fulfill(
                status=500, content_type="text/html", body="<h1>502 Bad Gateway</h1>",
            ),
        )
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")

        page.wait_for_selector("#status.error")
        assert "non-JSON response" in page.locator("#status").inner_text()
        assert "500" in page.locator("#status").inner_text()

    def test_response_missing_the_error_field_still_shows_something(
        self, page, live_url,
    ):
        page.route(
            "**/api/abstract",
            lambda route: route.fulfill(
                status=400, content_type="application/json", body="{}",
            ),
        )
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")

        page.wait_for_selector("#status.error")
        assert "Request failed (400)" in page.locator("#status").inner_text()

    def test_unexpected_extra_fields_in_a_successful_response_do_not_break_rendering(
        self, page, live_url,
    ):
        """
        A server that starts sending one extra top-level field tomorrow
        must not make the whole page blank today -- the renderer should
        read what it needs and ignore the rest.
        """
        def _augment(route):
            response = route.fetch()
            body = response.json()
            body["unexpected_future_field"] = {"nested": ["stuff", 1, None]}
            route.fulfill(response=response, json=body)

        page.route("**/api/abstract", _augment)
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert page.locator("#pane-original .code-line").count() > 0


class TestNetworkFailure:

    def test_connection_aborted_shows_a_recoverable_error(self, page, live_url):
        page.route("**/api/abstract", lambda route: route.abort("failed"))
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")

        page.wait_for_selector("#status.error")
        assert not page.is_disabled("#btn-abstract")
        assert page.is_hidden("#summary")

    def test_retry_after_a_network_failure_succeeds_once_the_network_returns(
        self, page, live_url,
    ):
        attempt = {"count": 0}

        def _flaky(route):
            attempt["count"] += 1
            if attempt["count"] == 1:
                route.abort("failed")
            else:
                route.continue_()

        page.route("**/api/abstract", _flaky)
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")

        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert attempt["count"] == 2


class TestLoadingState:

    def test_loading_indicator_and_disabled_controls_during_a_slow_request(
        self, page, live_url,
    ):
        def _slow(route):
            time.sleep(1.5)
            route.continue_()

        page.route("**/api/abstract", _slow)
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")

        assert page.is_disabled("#btn-abstract")
        assert "Abstracting" in page.locator("#status").inner_text()

        page.wait_for_selector("#summary:not([hidden])", timeout=10000)
        assert not page.is_disabled("#btn-abstract")

    def test_extremely_slow_response_does_not_freeze_other_interactions(
        self, page, live_url,
    ):
        """
        The page outside the busy buttons must stay interactive -- typing
        in an unrelated field, for instance -- while a request is pending.
        """
        def _slow(route):
            time.sleep(2)
            route.continue_()

        page.route("**/api/review", _slow)
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-review")

        page.fill("#query", "typed while a request is pending")
        assert page.input_value("#query") == "typed while a request is pending"

        page.wait_for_selector("#summary:not([hidden])", timeout=10000)


class TestStaleResponseOrdering:
    """
    Phase 9 asks whether an old response can overwrite a newer result.

    app.js's runAbstract/runReview attach ``.then(renderAll)`` to whichever
    promise their own call returned, with no request id or AbortController
    guarding it -- so *if* two requests were ever in flight together, a
    slow first one landing after a fast second one could repaint the page
    with stale data. The first version of this test tried to force exactly
    that with a delayed route and two rapid clicks, and found something
    more specific: it never got a second request to race against, because
    ``busy(true)`` (web/static/app.js) disables *both* action buttons
    synchronously, before ``fetch`` is even called -- and a browser does
    not dispatch a click handler on a ``disabled`` button at all, so the
    second click never reaches ``runAbstract``. There is no code path in
    this UI that puts two ``/api/abstract`` (or `/api/review`) requests in
    flight at once, which is what the tests below verify directly, rather
    than asserting it from reading the source.
    """

    def test_a_second_click_while_the_first_is_still_in_flight_fires_no_second_request(
        self, page, live_url,
    ):
        requests = []
        page.on("request", lambda r: requests.append(r.url)
                if r.method == "POST" and r.url.endswith("/api/abstract") else None)

        def _slow(route):
            time.sleep(1.5)
            route.continue_()

        page.route("**/api/abstract", _slow)
        page.goto(live_url + "/")
        page.fill("#source", "value_a = 111\n")
        page.click("#btn-abstract")

        assert page.is_disabled("#btn-abstract")
        assert page.is_disabled("#btn-review")
        # A real click event does not fire on a disabled control; force=True
        # bypasses Playwright's actionability check to prove that even a
        # forced dispatch is a no-op once the element is disabled.
        page.click("#btn-abstract", force=True, trial=False)
        page.click("#btn-review", force=True, trial=False)

        page.wait_for_selector("#summary:not([hidden])", timeout=10000)
        assert len(requests) == 1, (
            f"expected exactly one /api/abstract request, got {len(requests)}"
        )
        assert "value_a" in page.locator("#pane-original").inner_text()

    def test_two_sequential_submissions_render_the_second_ones_result(
        self, page, live_url,
    ):
        """
        The reachable version of "does a later result win": not concurrent
        (the UI forbids that), but back-to-back once the first has fully
        completed. Trivially safe if requests can never overlap, but worth
        stating as the positive claim this suite makes about ordering.

        Uses a polling assertion for the second submission rather than
        ``wait_for_selector("#summary:not([hidden])")`` -- #summary is
        already visible from the *first* run by this point, so that
        selector would match instantly without ever waiting for the
        second request, and the very next line would then read the first
        run's stale content. (Found by running this test: it originally
        used that selector and failed on exactly that stale read.)
        """
        page.goto(live_url + "/")
        page.fill("#source", "value_first = 1\n")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert "value_first" in page.locator("#pane-original").inner_text()

        page.fill("#source", "value_second = 2\n")
        page.click("#btn-abstract")
        expect(page.locator("#pane-original")).to_contain_text(
            "value_second", timeout=10000,
        )
        rendered = page.locator("#pane-original").inner_text()
        assert "value_first" not in rendered
