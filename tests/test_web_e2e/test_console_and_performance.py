"""
Phase 21 — browser console and network errors, captured across the main
workflows rather than asserted only on a single page load.

Phase 20 — frontend performance under a large response and rapid
interaction. Not a benchmark suite; a bound loose enough to be stable in
CI but tight enough that a real regression (e.g. an O(n^2) render loop
over source lines) would trip it.
"""

import time

from tests.test_web_e2e.conftest import CLEAN_SOURCE, SECRET_SOURCE


class TestConsoleAndNetworkAcrossWorkflows:

    def test_no_console_errors_across_abstract_review_and_sessions(
        self, page, live_url, console_errors, failed_requests,
    ):
        page.goto(live_url + "/")
        page.fill("#source", SECRET_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        for tab in ("vault", "raw", "mapped", "report"):
            page.click(f'[data-tab="{tab}"]')

        page.click("#btn-review")
        page.wait_for_selector("#tab-mapped:not([hidden])")

        page.goto(live_url + "/sessions")
        page.wait_for_load_state("networkidle")

        assert console_errors == [], f"console errors: {console_errors}"
        assert failed_requests == [], f"failed network requests: {failed_requests}"

    def test_no_console_errors_on_a_handled_validation_failure(
        self, page, live_url, console_errors,
    ):
        """
        An *expected* 400 (empty source) is application-level error
        handling: the fetch itself resolves, gets read as JSON, and its
        message is shown via setStatus -- app.js code runs, nothing throws
        uncaught. Chromium's devtools independently log any non-2xx fetch
        as a "Failed to load resource" console entry regardless of whether
        the page handled it (there is no way for page script to suppress
        this network-level log line), so that one specific, expected entry
        is allowed for; anything beyond it is not.
        """
        page.goto(live_url + "/")
        page.fill("#source", "")   # the page loads with sample code prefilled
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")
        assert console_errors == [
            "Failed to load resource: the server responded with a status of 400 (BAD REQUEST)"
        ]

    def test_sessions_translate_workflow_produces_no_console_errors(
        self, page, live_url, console_errors,
    ):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        page.goto(live_url + "/sessions")
        row_id = page.locator("#session-rows tr").first.get_attribute("data-session")
        page.fill("#translate-session", row_id)
        page.fill("#translate-text", "VAR_0 looks fine.")
        page.click("#btn-translate")
        page.wait_for_selector("#translate-output:not([hidden])")

        assert console_errors == []


class TestPerformance:

    def test_a_few_thousand_lines_abstracts_and_renders_within_a_generous_bound(
        self, page, live_url,
    ):
        lines = [f"variable_{i} = {i}" for i in range(3000)]
        code = "\n".join(lines) + "\n"

        page.goto(live_url + "/")
        page.eval_on_selector(
            "#source",
            "(el, value) => { el.value = value; }",
            code,
        )
        start = time.monotonic()
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])", timeout=30000)
        elapsed = time.monotonic() - start

        # 3001, not 3000: the trailing newline in `code` produces one
        # extra, empty final line when split on '\n' -- see the same note
        # in test_export_navigation.py.
        assert page.locator("#pane-original .code-line").count() == 3001
        # Generous on purpose (this covers AST parsing, network, and
        # rendering 3000 DOM rows) -- the point is catching a real
        # regression (minutes, or a hang), not chasing a tight budget.
        assert elapsed < 20, f"took {elapsed:.1f}s for 3000 lines"

    def test_switching_tabs_repeatedly_stays_responsive(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", SECRET_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        start = time.monotonic()
        for _ in range(20):
            for tab in ("vault", "raw", "mapped", "report"):
                page.click(f'[data-tab="{tab}"]')
        elapsed = time.monotonic() - start
        assert elapsed < 15, f"80 tab switches took {elapsed:.1f}s"
        assert page.is_visible("#tab-report")
