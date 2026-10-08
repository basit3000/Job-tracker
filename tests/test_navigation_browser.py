"""Navigation remains discoverable and keyboard usable across screen sizes."""

import os
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from tests.test_reference_client import QuietHandler


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and install Chromium.",
)
@pytest.mark.parametrize("width", [1440, 1024, 768, 390, 320])
def test_responsive_navigation_and_keyboard_controls(app, users, width):
    from playwright.sync_api import expect, sync_playwright

    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    artifacts = Path(__file__).resolve().parents[1] / ".venv/browser-review"
    artifacts.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/login")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            nav = page.get_by_role("navigation", name="Main navigation")
            for name in (
                "Home",
                "My tracker",
                "People",
            ):
                expect(
                    nav.get_by_role("link", name=name, exact=True)
                ).to_be_visible()
            expect(nav.get_by_role("link", name="Home")).to_have_attribute(
                "aria-current", "page"
            )
            expect(
                page.get_by_role("link", name="Add application", exact=True)
            ).to_have_count(1)
            expect(
                page.get_by_text("owner@example.com", exact=True)
            ).not_to_be_visible()
            page.screenshot(
                path=str(artifacts / f"navigation-overview-{width}.png"),
                full_page=True,
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )

            nav.get_by_role("link", name="My tracker", exact=True).click()
            views = page.get_by_role("navigation", name="Application views")
            views.get_by_role("link", name="Status board", exact=True).click()
            expect(
                nav.get_by_role("link", name="My tracker")
            ).to_have_attribute("aria-current", "true")
            expect(
                views.get_by_role("link", name="Status board")
            ).to_have_attribute("aria-current", "page")
            views.get_by_role("link", name="Applications", exact=True).click()
            expect(
                views.get_by_role("link", name="Applications")
            ).to_have_attribute("aria-current", "page")

            if width < 768:
                menu = page.get_by_role("button", name="Menu", exact=True)
                menu.click()
                expect(menu).to_have_attribute("aria-expanded", "true")
                expect(
                    page.get_by_role("link", name="Import & sync", exact=False)
                ).to_be_visible()
                expect(
                    page.get_by_role(
                        "link", name="Account settings", exact=True
                    )
                ).to_be_visible()
                page.screenshot(
                    path=str(artifacts / f"navigation-menu-{width}.png"),
                    full_page=True,
                )
                page.keyboard.press("Escape")
                expect(menu).to_be_focused()
                expect(menu).to_have_attribute("aria-expanded", "false")
                expect(
                    page.get_by_role(
                        "link", name="Account settings", exact=True
                    )
                ).not_to_be_visible()
                menu.click()
            else:
                account = page.get_by_role(
                    "button", name="Account", exact=True
                )
                account.focus()
                page.keyboard.press("Enter")
                expect(account).to_have_attribute("aria-expanded", "true")
                page.keyboard.press("Escape")
                expect(account).to_be_focused()
                expect(account).to_have_attribute("aria-expanded", "false")
                page.get_by_role(
                    "button", name="Data tools", exact=True
                ).click()
                expect(page.locator("#dataToolsToggle")).to_have_attribute(
                    "aria-expanded", "true"
                )
                expect(
                    page.get_by_role(
                        "link", name="Export applications", exact=False
                    )
                ).to_be_visible()
                page.screenshot(
                    path=str(artifacts / f"navigation-menu-{width}.png"),
                    full_page=False,
                )
            expect(
                page.locator('.header-menu a[href="/imports"]')
            ).to_have_count(1)
            expect(
                page.locator('.header-menu a[href="/sources"]')
            ).to_have_count(0)
            page.get_by_role(
                "link", name="Export applications", exact=False
            ).click()
            expect(page).to_have_url(origin + "/exports")

            page.goto(origin + "/dashboard")
            page.keyboard.press("Tab")
            expect(
                page.get_by_role("link", name="Skip to content")
            ).to_be_focused()
            page.keyboard.press("Enter")
            expect(page.locator("#main-content")).to_be_focused()
            if width < 768:
                page.get_by_role("button", name="Menu", exact=True).click()
                page.set_viewport_size({"width": 1024, "height": 900})
                page.set_viewport_size({"width": width, "height": 900})
                expect(
                    page.get_by_role("button", name="Menu", exact=True)
                ).to_have_attribute("aria-expanded", "false")
                expect(
                    page.get_by_role(
                        "link", name="Account settings", exact=True
                    )
                ).not_to_be_visible()
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
