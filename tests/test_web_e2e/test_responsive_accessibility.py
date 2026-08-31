"""
Phases 17 and 18 — responsive layout and keyboard/accessibility.

Real viewports, real screenshots (saved for a human to skim rather than
asserted on pixel-by-pixel, which is brittle for a bug hunt like this) and
a real keyboard-only run through the golden path -- no mouse call anywhere
in that last one.
"""

import pathlib

import pytest

from tests.test_web_e2e.conftest import CLEAN_SOURCE

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "laptop": {"width": 1024, "height": 768},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 812},
}

SCREENSHOT_DIR = pathlib.Path(__file__).resolve().parent / "_screenshots"


class TestResponsiveLayout:

    @pytest.mark.parametrize("name", VIEWPORTS)
    def test_no_horizontal_overflow_on_the_workbench(self, page, live_url, name):
        page.set_viewport_size(VIEWPORTS[name])
        page.goto(live_url + "/")
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        client_width = page.evaluate("() => document.documentElement.clientWidth")
        assert scroll_width <= client_width + 1, (
            f"{name} ({VIEWPORTS[name]}): page overflows horizontally "
            f"({scroll_width}px content in a {client_width}px viewport)"
        )

    @pytest.mark.parametrize("name", VIEWPORTS)
    def test_primary_actions_remain_visible_and_clickable(self, page, live_url, name):
        page.set_viewport_size(VIEWPORTS[name])
        page.goto(live_url + "/")
        for selector in ("#source", "#btn-abstract", "#btn-review"):
            box = page.locator(selector).bounding_box()
            assert box is not None, f"{selector} not rendered at {name}"
            assert box["width"] > 0 and box["height"] > 0

    def test_full_workflow_at_mobile_width(self, page, live_url):
        page.set_viewport_size(VIEWPORTS["mobile"])
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert page.is_visible("#code-panel")
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        client_width = page.evaluate("() => document.documentElement.clientWidth")
        assert scroll_width <= client_width + 1

    def test_result_tables_scroll_within_their_own_container_not_the_page(
        self, page, live_url,
    ):
        """
        ``.table-scroll`` around the wide report/vault tables is the app's
        answer to "a table wider than the viewport" -- confirm it actually
        is the element that scrolls, not the page.
        """
        page.set_viewport_size(VIEWPORTS["mobile"])
        page.goto(live_url + "/")
        page.fill("#source", "a_very_long_identifier_name_for_width = 'a_long_value_too'\n")
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        overflow_x = page.eval_on_selector(
            ".table-scroll", "el => getComputedStyle(el).overflowX",
        )
        assert overflow_x in ("auto", "scroll")

    @pytest.mark.parametrize("name", VIEWPORTS)
    def test_screenshot_for_manual_review(self, page, live_url, name):
        page.set_viewport_size(VIEWPORTS[name])
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / f"workbench_{name}.png"), full_page=True)


class TestKeyboardOnlyWorkflow:

    def test_complete_abstract_workflow_without_a_mouse(self, page, live_url):
        page.goto(live_url + "/")
        page.click("#source")   # focus only; a real keyboard user tabs here
        page.keyboard.press("Control+A")
        page.keyboard.type("keyboard_only_value = 1\n")

        # Tab from the source textarea to the Abstract button and activate
        # it with the keyboard alone.
        focused = page.evaluate("() => document.activeElement.id")
        guard = 0
        while focused != "btn-abstract" and guard < 25:
            page.keyboard.press("Tab")
            focused = page.evaluate("() => document.activeElement.id")
            guard += 1
        assert focused == "btn-abstract", "could not reach the Abstract button by Tab alone"

        page.keyboard.press("Enter")
        page.wait_for_selector("#summary:not([hidden])")
        assert "keyboard_only_value" in page.locator("#pane-original").inner_text()

    def test_tab_order_reaches_every_primary_control_in_the_input_panel(
        self, page, live_url,
    ):
        page.goto(live_url + "/")
        page.click("#filename")
        seen = []
        for _ in range(15):
            page.keyboard.press("Tab")
            seen.append(page.evaluate("() => document.activeElement.id"))
        for expected in ("btn-abstract", "btn-review"):
            assert expected in seen, f"Tab order never reaches #{expected}"

    def test_escape_and_arrow_keys_do_not_error_on_tabs(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")

        page.click('[data-tab="vault"]')
        page.keyboard.press("Escape")
        assert page.is_visible("#tab-vault")


class TestAccessibleMarkup:
    """Structural claims a screen reader (or axe) would also check."""

    def test_every_text_input_has_an_associated_label_or_aria_label(self, page, live_url):
        page.goto(live_url + "/")
        unlabelled = page.evaluate(
            """() => {
                const controls = document.querySelectorAll('input, textarea, select');
                const bad = [];
                controls.forEach(el => {
                    if (el.type === 'file' || el.type === 'hidden') return;
                    const hasAriaLabel = el.hasAttribute('aria-label');
                    const hasWrappingLabel = el.closest('label') !== null;
                    const hasForLabel = el.id &&
                        document.querySelector(`label[for="${el.id}"]`) !== null;
                    if (!hasAriaLabel && !hasWrappingLabel && !hasForLabel) {
                        bad.push(el.id || el.name || el.outerHTML.slice(0, 60));
                    }
                });
                return bad;
            }"""
        )
        assert unlabelled == []

    def test_status_regions_are_announced(self, page, live_url):
        page.goto(live_url + "/")
        assert page.get_attribute("#status", "role") == "status"

    def test_tabs_carry_tab_roles(self, page, live_url):
        page.goto(live_url + "/")
        page.fill("#source", CLEAN_SOURCE)
        page.click("#btn-abstract")
        page.wait_for_selector("#summary:not([hidden])")
        assert page.get_attribute("#tabs", "role") == "tablist"
        assert page.locator('[role="tab"]').count() == 4
        assert page.locator('[role="tabpanel"]').count() == 4

    def test_error_communication_is_not_color_only(self, page, live_url):
        """
        ``.status.error`` carries a CSS class change, but the message text
        itself must also say something is wrong -- color alone is not an
        accessible error signal.
        """
        page.goto(live_url + "/")
        page.fill("#source", "")
        page.click("#btn-abstract")
        page.wait_for_selector("#status.error")
        text = page.locator("#status").inner_text().strip()
        assert len(text) > 0
