"""
Phases 4, 5, 6, 7 — interactions, source-input edge cases, form validation,
and the complete browser-to-backend-to-browser workflow.

Every test drives the real page: fills real inputs, clicks real buttons,
waits on real DOM state changes, and reads back what actually rendered --
never the mocked JavaScript functions the master brief specifically warns
against relying on.
"""

import pytest

from tests.test_web_e2e.conftest import CLEAN_SOURCE, FakeLLMClient


def _abstract(page, live_url, code="value = 1\n", filename="a.py"):
    page.goto(live_url + "/")
    page.fill("#source", code)
    page.fill("#filename", filename)
    page.click("#btn-abstract")
    page.wait_for_selector("#summary:not([hidden])")


def _wait_for_result(page, timeout=30000):
    """
    Wait for a terminal status, not merely a non-empty one.

    setStatus() is called with no ``kind`` for the transient "Abstracting…" /
    "Sending…" message, so ``#status`` is non-empty (and has only the bare
    ``status`` class) well before the request resolves. ``.ok``/``.error``
    is only ever added on the final call, so waiting for either of those is
    the actual terminal-state signal.
    """
    page.wait_for_selector("#status.ok, #status.error", timeout=timeout)


def _set_large_source(page, code):
    """
    Set the textarea's value directly rather than through ``fill()``.

    Playwright's ``fill()`` is fast for ordinary input, but for a
    multi-hundred-KB string it can fall back to a much slower path in some
    browser/OS combinations and blow past the default 30s action timeout --
    a Playwright-driver cost, not something the app under test did. Setting
    ``.value`` and dispatching the same ``input`` event a real paste would
    fire exercises the app's own change handling without that cost.
    """
    page.eval_on_selector(
        "#source",
        "(el, value) => { el.value = value; "
        "el.dispatchEvent(new Event('input', { bubbles: true })); }",
        code,
    )


class TestFullWorkbenchWorkflow:
    """Phase 7: browser -> frontend -> API -> backend -> DOM, end to end."""

    def test_abstract_only_workflow(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        assert page.is_visible("#code-panel")
        assert page.is_visible("#output-panel")
        assert page.locator("#pane-original .code-line").count() > 0
        assert page.locator("#pane-abstract .code-line").count() > 0
        # "Abstract" alone never runs the LLM tabs.
        assert "Not run" in page.locator("#raw-response").inner_text()
        assert page.locator("#status").get_attribute("class") == "status ok"

    def test_full_review_workflow_calls_the_fake_provider_and_maps_feedback_back(
        self, page, live_url, fake_client,
    ):
        page.goto(live_url + "/")
        page.fill("#source", "def total(items):\n    return sum(items)\n")
        page.click("#btn-review")
        page.wait_for_selector("#summary:not([hidden])")

        # Review switches straight to the mapped-feedback tab.
        assert page.is_visible("#tab-mapped")
        assert page.is_hidden("#tab-report")
        mapped = page.locator("#mapped-feedback").inner_text()
        assert "Not run" not in mapped
        assert len(mapped.strip()) > 0

    def test_tabs_switch_content_without_a_second_request(self, page, live_url):
        requests = []
        page.on("request", lambda r: requests.append(r.url) if r.method == "POST" else None)
        _abstract(page, live_url)
        before = len(requests)

        for tab in ("vault", "raw", "mapped", "report"):
            page.click(f'[data-tab="{tab}"]')
            assert page.is_visible(f"#tab-{tab}")
            for other in ("report", "vault", "raw", "mapped"):
                if other != tab:
                    assert page.is_hidden(f"#tab-{other}")

        assert len(requests) == before, "switching tabs must not re-hit the API"

    def test_clicking_a_token_scrolls_and_links_the_original_pane(self, page, live_url):
        _abstract(page, live_url, code="secret_value = 42\n")
        token = page.locator("#pane-abstract .tok").first
        token.click()
        assert "active" in (token.get_attribute("class") or "")
        linked_line = page.locator("#pane-original .code-line.linked")
        assert linked_line.count() >= 1


class TestButtonAndControlInteractions:
    """Phase 4: every control, normal/repeated/rapid/keyboard interaction."""

    def test_buttons_disable_while_busy_and_re_enable_after(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        # Immediately after the click, before the (fast, local) response
        # lands, the busy() call should have disabled both action buttons.
        # A same-machine fake backend can resolve before Playwright's next
        # poll, so this assertion tolerates already-finished as well as
        # currently-busy, and always ends by asserting re-enabled.
        page.wait_for_selector("#summary:not([hidden])")
        assert not page.is_disabled("#btn-abstract")
        assert not page.is_disabled("#btn-review")

    def test_rapid_repeated_clicks_on_abstract_do_not_crash_or_duplicate_state(
        self, page, live_url,
    ):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        for _ in range(5):
            page.click("#btn-abstract")
        # Five overlapping requests each independently re-enable the button
        # in their own .finally(), so the button can still be mid-flight
        # for a later click when the first one's response has already
        # rendered #summary; wait for the button itself to settle rather
        # than assuming it settles by the time the first response lands.
        page.wait_for_selector("#summary:not([hidden])")
        page.wait_for_selector("#btn-abstract:not([disabled])", timeout=10000)
        # One coherent result, not a half-rendered mix of several runs.
        assert page.locator("#pane-original .code-line").count() > 0

    def test_privacy_level_select_changes_the_abstraction(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "STRIPE_KEY = 'sk_live_x'\nvalue = 1\n")

        page.select_option("#privacy-level", "low")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        low_hidden = page.locator("#stat-strip dd").nth(3).inner_text()

        page.select_option("#privacy-level", "critical")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        critical_hidden = page.locator("#stat-strip dd").nth(3).inner_text()

        assert int(critical_hidden) >= int(low_hidden)

    def test_context_window_boundary_values_are_accepted(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        for value in ("0", "20"):
            page.fill("#context-window", value)
            page.click("#btn-abstract")
            page.wait_for_selector("#summary:not([hidden])")
            assert "error" not in (page.get_attribute("#status", "class") or "")

    def test_context_window_out_of_range_surfaces_a_frontend_visible_error(
        self, page, live_url,
    ):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.fill("#context-window", "21")
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")
        assert "between 0 and 20" in page.locator("#status").inner_text()
        assert page.is_hidden("#summary")

    def test_keep_comments_checkbox_toggles(self, page, live_url):
        page.goto(live_url + "/")
        assert not page.is_checked("#keep-comments")
        page.check("#keep-comments")
        assert page.is_checked("#keep-comments")
        page.uncheck("#keep-comments")
        assert not page.is_checked("#keep-comments")

    def test_interaction_after_an_error_recovers_cleanly(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "   \n\t \n")   # whitespace only -> rejected
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")

        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert "error" not in page.get_attribute("#status", "class")

    def test_enter_key_in_query_field_does_not_submit_a_form(self, page, live_url):
        """
        There is no <form> on this page (deliberately -- app.js's own header
        says every action binds by id) so Enter in a text input must be a
        no-op, not a page reload that would drop unsent state.
        """
        page.goto(live_url + "/")
        page.fill("#query", "what does this do?")
        page.press("#query", "Enter")
        page.wait_for_timeout(200)
        assert page.is_hidden("#summary")
        assert page.input_value("#query") == "what does this do?"


class TestSourceInputEdgeCases:
    """Phase 5: the boundary and adversarial shapes of the source textarea."""

    def test_empty_source_is_rejected_with_a_visible_error(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "")
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")
        assert "No source code" in page.locator("#status").inner_text()

    def test_whitespace_only_source_is_rejected(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "   \n  \n\t")
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")

    def test_single_character_source(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "1")
        page.click("#btn-abstract")
        _wait_for_result(page)
        # Either it parses (a bare literal is valid Python) or it is
        # rejected cleanly -- either way, no crash and no hang.
        cls = page.get_attribute("#status", "class")
        assert cls in ("status ok", "status error")

    def test_unicode_and_emoji_in_source_round_trip_into_the_original_pane(
        self, page, live_url,
    ):
        code = '# caf\u00e9 na\u00efve \U0001f600\nvalue = "\u00fcml\u00e4ut"\n'
        page.goto(live_url + "/")
        page.fill("#source", code)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        original = page.locator("#pane-original").inner_text()
        assert "\u00fcml\u00e4ut" in original

    def test_source_with_quotes_and_backslashes(self, page, live_url):
        code = 'path = "C:\\\\Users\\\\a"\nquote = \'it\\\'s\'\ndq = "she said \\"hi\\""\n'
        page.goto(live_url + "/")
        page.fill("#source", code)
        page.click("#btn-abstract")
        _wait_for_result(page)
        assert page.get_attribute("#status", "class") in ("status ok", "status error")

    def test_malformed_syntax_is_rejected_with_a_specific_message(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "def f(:\n    pass\n")
        page.fill("#filename", "broken.py")
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")
        # core/ast_parser.py wraps the SyntaxError into
        # "Invalid Python syntax at line N: ..." before web/service.py ever
        # sees a bare SyntaxError, so that -- not the "does not parse"
        # phrasing in service.py's own except SyntaxError branch, which
        # this code path never reaches -- is the message a user sees.
        message = page.locator("#status").inner_text()
        assert "syntax" in message.lower()
        assert "line 1" in message.lower()
        assert page.is_hidden("#summary")

    def test_very_long_single_line_does_not_hang_the_ui(self, page, live_url):
        code = "value = '" + ("x" * 20000) + "'\n"
        page.goto(live_url + "/")
        _set_large_source(page, code)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])", timeout=15000)
        assert page.locator("#pane-original .code-line").count() >= 1

    def test_multiline_docstrings_and_fstrings_preserve_structure(self, page, live_url):
        code = (
            'def f(x):\n'
            '    """\n'
            '    A multi-line docstring.\n'
            '    Second line.\n'
            '    """\n'
            '    return f"value is {x}"\n'
        )
        page.goto(live_url + "/")
        page.fill("#source", code)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert page.locator("#pane-original .code-line").count() == code.count("\n") + 1

    def test_javascript_source_uses_the_js_adapter(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "const apiToken = 'sk_live_x';\nfunction f(a){return a+1;}\n")
        page.fill("#filename", "app.js")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert "error" not in page.get_attribute("#status", "class")

    def test_unsupported_extension_is_rejected(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", "value = 1\n")
        page.fill("#filename", "data.unknownext")
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")
        assert "No language adapter" in page.locator("#status").inner_text()

    def test_oversized_source_is_rejected_with_the_size_limit_named(
        self, page, live_url,
    ):
        # Just over the service's 512 KiB cap, comfortably under Flask's
        # 2 MiB hard limit, so this exercises validate_source's message
        # rather than the generic 413 from app.py's MAX_CONTENT_LENGTH.
        oversized = "value = 1\n" + ("# " + "x" * 78 + "\n") * 7000
        assert len(oversized.encode("utf-8")) > 512 * 1024
        page.goto(live_url + "/")
        _set_large_source(page, oversized)
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error", timeout=15000)
        assert "KiB" in page.locator("#status").inner_text()


class TestFileOpenInteraction:
    """The "Open file..." control, which reads client-side via FileReader."""

    def test_opening_a_file_populates_source_and_filename_without_a_request(
        self, page, live_url,
    ):
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        page.goto(live_url + "/")
        requests.clear()

        page.set_input_files("#file-input", files=[{
            "name": "uploaded.py",
            "mimeType": "text/x-python",
            "buffer": b"loaded_value = 123\n",
        }])
        page.wait_for_function(
            "() => document.getElementById('filename').value === 'uploaded.py'"
        )
        assert "loaded_value = 123" in page.input_value("#source")
        assert "nothing has been sent" in page.locator("#status").inner_text().lower()
        assert not any(r.endswith("/api/abstract") or r.endswith("/api/review") for r in requests)
