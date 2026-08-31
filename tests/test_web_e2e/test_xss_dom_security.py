"""
Phase 11/12 — XSS and DOM-injection testing, executed in a real browser.

Static audit first (this is the Phase 12 "trace every dynamic sink" part,
done by reading the code rather than guessing): ``web/static/app.js`` and
``sessions.js`` use ``innerHTML`` in exactly four places, and the module
header of each file states the rule -- innerHTML only for the ``html`` /
``*_html`` fields the server escaped in ``web/highlight.py``, everything
else via ``textContent``. ``web/highlight.py`` escapes with ``html.escape``
before any markup is added, and the token/name substitution afterward
matches on a fixed token grammar (``PREFIX_\\d+``) that ``html.escape``
provably cannot produce.

That is a sound design *on paper*. The point of this file is to stop
reading and start attacking it: feed the same payloads a real adversary
would through every field a browser lets a user control -- source, filename,
the free-form query, and (since the fake LLM client's reply is
attacker-controllable in the same way a compromised or careless real
provider's would be) the "LLM" response text -- and watch whether a script
actually runs.
"""

import json

import pytest

from tests.test_web_e2e.conftest import FakeLLMClient

XSS_PAYLOADS = [
    '<script>window.__xss_fired = "script"</script>',
    '<img src=x onerror="window.__xss_fired=\'img\'">',
    '<svg onload="window.__xss_fired=\'svg\'"></svg>',
    '"><script>window.__xss_fired = "attr-break"</script>',
    "javascript:window.__xss_fired='href'",
    '<iframe src="javascript:window.__xss_fired=\'iframe\'"></iframe>',
]


@pytest.fixture(autouse=True)
def _xss_marker(page):
    """A page-scoped flag any successful payload would set."""
    page.add_init_script("window.__xss_fired = false;")


def _xss_fired(page) -> bool:
    return page.evaluate("() => window.__xss_fired")


class TestSourceInputXSS:
    """The most obvious vector: paste a payload as source code."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_payload_in_source_does_not_execute(self, page, live_url, payload):
        # json.dumps, not an f-string: several payloads contain their own
        # unescaped double quotes, which inside a naively-quoted f-string
        # produced invalid Python (a real SyntaxError -> 400) rather than
        # actually exercising the escaping this test means to attack.
        code = f'comment_field = {json.dumps(payload)}\nvalue = 1\n'
        page.goto(live_url + "/")
        page.fill("#source", code)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        assert _xss_fired(page) is False
        # The payload must render as inert text somewhere (original pane,
        # verbatim), never as live markup.
        assert page.locator("#pane-original script").count() == 0
        assert page.locator("#pane-abstract script").count() == 0


class TestFilenameXSS:
    """Filename is attacker-controlled and echoed into session listings."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS[:3])
    def test_payload_as_filename_does_not_execute_on_workbench_or_sessions(
        self, page, live_url, payload,
    ):
        page.goto(live_url + "/")
        page.fill("#source", "value = 1\n")
        page.fill("#filename", f"{payload}.py")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert _xss_fired(page) is False

        page.goto(live_url + "/sessions")
        assert _xss_fired(page) is False
        assert page.locator("#session-rows script").count() == 0


class TestQueryXSS:
    """The free-form question, abstracted and later rendered back."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS[:3])
    def test_payload_in_query_does_not_execute(self, page, live_url, payload):
        page.goto(live_url + "/")
        page.fill("#source", "value = 1\n")
        page.fill("#query", payload)
        page.click("#btn-review")
        page.wait_for_selector("#summary:not([hidden])")
        assert _xss_fired(page) is False


class TestProviderResponseXSS:
    """
    A provider's answer is exactly as adversarial as this suite has to
    assume: it is untrusted text arriving over the network, being placed
    into the DOM. The fake client stands in for a compromised or merely
    buggy real one.
    """

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_malicious_llm_reply_does_not_execute(self, page, live_server_factory, payload):
        client = FakeLLMClient(reply=f"VAR_0 looks fine. {payload} Also check VAR_1.")
        live_url = live_server_factory(client=client)

        page.goto(live_url + "/")
        page.fill("#source", "value = 1\nother = 2\n")
        page.click("#btn-review")
        page.wait_for_selector("#summary:not([hidden])")

        assert _xss_fired(page) is False
        page.click('[data-tab="raw"]')
        page.click('[data-tab="mapped"]')
        assert page.locator("#raw-response script").count() == 0
        assert page.locator("#mapped-feedback script").count() == 0


class TestTranslatePageXSS:
    """/sessions' translate box renders provider text through the same path."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS[:3])
    def test_malicious_pasted_response_does_not_execute(
        self, page, live_url, payload,
    ):
        page.goto(live_url + "/")
        page.fill("#source", "value = 1\n")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        session_id = page.eval_on_selector("#status", "el => el.textContent")

        page.goto(live_url + "/sessions")
        # Any row's id will do; pull one from the table rather than parsing
        # the status string, which only carries a shortened prefix.
        first_row_id = page.locator("#session-rows tr").first.get_attribute("data-session")
        page.fill("#translate-session", first_row_id)
        page.fill("#translate-text", f"VAR_0 is fine. {payload}")
        page.click("#btn-translate")
        page.wait_for_selector("#translate-output:not([hidden])")

        assert _xss_fired(page) is False
        assert page.locator("#translate-output script").count() == 0


class TestDomSinkAudit:
    """
    Static confirmation of the Phase 12 sink inventory, run as a test so a
    future change to app.js/sessions.js that adds a new innerHTML/eval/
    document.write call is caught by CI rather than by the next adversarial
    pass.
    """

    def test_no_new_dangerous_sinks_introduced(self):
        import pathlib
        import re

        static_dir = pathlib.Path(__file__).resolve().parents[2] / "web" / "static"
        dangerous = re.compile(r"\.outerHTML\s*=|document\.write\(|\beval\(|new Function\(")
        offenders = []
        for js_file in static_dir.glob("*.js"):
            text = js_file.read_text(encoding="utf-8")
            if dangerous.search(text):
                offenders.append(js_file.name)
        assert offenders == [], f"dangerous sink introduced in: {offenders}"

    def test_every_innerhtml_assignment_is_a_server_escaped_field(self):
        """
        Every ``.innerHTML =`` right-hand side must be one of the fields
        ``web/highlight.py`` escapes (``line.html``, ``*_html`` responses),
        never a raw user-controlled variable assembled client-side.
        """
        import pathlib
        import re

        static_dir = pathlib.Path(__file__).resolve().parents[2] / "web" / "static"
        for js_file in static_dir.glob("*.js"):
            text = js_file.read_text(encoding="utf-8")
            assignments = re.findall(r"\.innerHTML\s*=\s*[^;]+;", text)
            for assignment in assignments:
                assert "_html" in assignment or ".html" in assignment, (
                    f"suspicious innerHTML assignment in {js_file.name}: {assignment!r}"
                )
