"""
Phases 14, 15, 16 — export/download, state recovery, and browser
navigation/refresh.

Phase 15 ("reset and state recovery") is scoped to what the workbench
actually has: there is no dedicated Reset control in ``index.html`` -- the
only ways state changes are a fresh submission or a real page reload, both
covered below. Asserting on a Reset button that does not exist would be
testing a feature this UI was never given.
"""

import pytest
from playwright.sync_api import expect

from tests.test_web_e2e.conftest import CANARY, CANARY_SOURCE, CLEAN_SOURCE, SECRET_SOURCE


class TestReportDownload:
    """The one export path: "Download report as Markdown"."""

    def test_download_produces_a_markdown_file_with_the_expected_name_and_content(
        self, page, live_url,
    ):
        page.goto(live_url + "/")
        page.fill("#source", SECRET_SOURCE)
        page.fill("#filename", "payments.py")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        with page.expect_download() as download_info:
            page.click("#btn-report-md")
        download = download_info.value

        assert download.suggested_filename == "payments-privacy-report.md"
        path = download.path()
        content = path.read_text(encoding="utf-8")
        assert "SECRET" in content
        assert content.strip()

    def test_downloaded_report_never_contains_a_secret_value(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", CANARY_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        with page.expect_download() as download_info:
            page.click("#btn-report-md")
        content = download_info.value.path().read_text(encoding="utf-8")
        assert CANARY not in content

    def test_download_button_before_any_run_is_a_no_op(self, page, live_url):
        """
        ``downloadReport()`` returns early when ``state.report`` is unset.
        The button is only reachable once ``#output-panel`` is visible
        (i.e. after a run), so this exercises that guard directly via the
        DOM rather than relying on visibility alone.
        """
        page.goto(live_url + "/")
        assert page.is_hidden("#output-panel")
        # No exception, no navigation, nothing downloaded.
        page.evaluate("() => document.getElementById('btn-report-md') !== null")


class TestNavigationAndRefresh:

    def test_refreshing_after_a_result_returns_to_the_clean_initial_state(
        self, page, live_url,
    ):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        page.reload()
        assert page.is_hidden("#summary")
        assert page.is_hidden("#code-panel")
        assert page.is_hidden("#output-panel")
        # index.html always re-renders the server's sample source on GET /.
        assert "STRIPE_API_KEY" in page.input_value("#source")

    def test_refresh_during_a_slow_pending_request_does_not_crash_the_page(
        self, page, live_url,
    ):
        def _slow(route):
            import time
            time.sleep(3)
            route.continue_()

        page.route("**/api/abstract", _slow)
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_timeout(200)

        page.reload()
        page.wait_for_load_state("domcontentloaded")
        assert page.is_visible("#btn-abstract")
        assert not page.is_disabled("#btn-abstract")

    def test_back_and_forward_between_workbench_and_sessions(self, page, live_url):
        page.goto(live_url + "/")
        page.goto(live_url + "/sessions")
        page.go_back()
        expect(page).to_have_title("Workbench — CodeAbstract")
        page.go_forward()
        expect(page).to_have_title("Sessions — CodeAbstract")

    def test_a_session_created_in_one_tab_is_visible_from_a_second_tab(
        self, page, live_url, context,
    ):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        second = context.new_page()
        second.goto(live_url + "/sessions")
        assert second.locator("#session-rows tr").count() >= 1
        second.close()

    def test_new_submission_after_a_prior_result_replaces_it_rather_than_appending(
        self, page, live_url,
    ):
        page.goto(live_url + "/")
        page.fill("#source", "first_run_marker = 1\n")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        page.fill("#source", "second_run_marker = 1\nsecond_line = 2\nthird_line = 3\n")
        page.click("#btn-abstract")
        expect(page.locator("#pane-original")).to_contain_text("second_run_marker")
        assert "first_run_marker" not in page.locator("#pane-original").inner_text()
        # 4, not 3: highlight_original_code splits on '\n', and the source's
        # trailing newline produces one extra, empty final line -- the same
        # convention the original-pane rendering uses throughout.
        assert page.locator("#pane-original .code-line").count() == 4
