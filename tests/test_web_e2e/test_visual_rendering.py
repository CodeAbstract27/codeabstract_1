"""
Real-browser checks for two defects that only showed up by actually
looking at a rendered page, not by reading response bodies:

1. The Dashboard/Insights bar charts used to write
   ``style="height: N%"`` directly, which the app's own CSP
   (``style-src 'self'``, see web/app.py) silently blocks -- every bar
   rendered at 0% height, with no error visible anywhere except the
   browser console. Fixed by bucketing percentages into CSS classes
   (``pct_class`` in web/app.py) instead of ever writing an inline style.

2. The panel entrance animation (``@keyframes panel-in`` in app.css)
   originally animated ``opacity`` from 0 to 1. In this headless browser,
   that animation was observed stuck mid-playback (``animationPlayState``
   reported ``running`` indefinitely, opacity frozen at its start value),
   which made the login/signup card invisible outright. Fixed by animating
   only ``transform`` -- never opacity -- so a stuck or throttled
   animation degrades to "sitting 4px off" instead of "gone".

Both are regressions no test-client-based test (tests/test_web/) can
catch, since that client never applies a CSP or runs CSS.
"""

import pytest


def _no_inline_style_attrs(page) -> bool:
    return page.eval_on_selector_all(
        '[style]', 'els => els.length',
    ) == 0


class TestNoCspBlockedStyles:
    def test_login_page_has_no_inline_styles_and_is_visible(self, page, live_url, console_errors):
        page.goto(live_url + "/login")
        assert _no_inline_style_attrs(page)
        opacity = page.eval_on_selector('.auth-panel', 'el => getComputedStyle(el).opacity')
        assert opacity == '1'
        assert not any('Content Security Policy' in e for e in console_errors)

    def test_signup_page_has_no_inline_styles_and_is_visible(self, page, live_url, console_errors):
        page.goto(live_url + "/signup")
        assert _no_inline_style_attrs(page)
        opacity = page.eval_on_selector('.auth-panel', 'el => getComputedStyle(el).opacity')
        assert opacity == '1'
        assert not any('Content Security Policy' in e for e in console_errors)

    def test_dashboard_bar_chart_renders_a_nonzero_bar(self, page, live_server_factory, fake_client):
        live_url = live_server_factory(client=fake_client)

        page.goto(live_url + "/signup")
        page.fill('#email', 'e2e-visual@example.com')
        page.fill('#password', 'testpassword1')
        page.click('button[type=submit]')
        page.wait_for_url('**/dashboard')

        page.request.post(
            live_url + '/api/abstract',
            data='{"code": "API_KEY = \\"sk_live_abc123def456ghi789\\"\\ndef f(x):\\n    return x + 1\\n", "filename": "a.py"}',
            headers={'Content-Type': 'application/json'},
        )
        page.goto(live_url + "/dashboard")
        page.wait_for_selector('.bar-fill')

        assert _no_inline_style_attrs(page)

        heights = page.eval_on_selector_all(
            '.bar-fill', 'els => els.map(e => parseFloat(getComputedStyle(e).height))',
        )
        # At least one day's bar must be visibly taller than the 2px
        # min-height floor every bar gets regardless of its data.
        assert max(heights) > 2

    def test_insights_page_has_no_inline_styles(self, page, live_url, console_errors):
        page.goto(live_url + "/signup")
        page.fill('#email', 'e2e-visual-insights@example.com')
        page.fill('#password', 'testpassword1')
        page.click('button[type=submit]')
        page.wait_for_url('**/dashboard')

        page.goto(live_url + "/insights")
        assert _no_inline_style_attrs(page)
        assert not any('Content Security Policy' in e for e in console_errors)
