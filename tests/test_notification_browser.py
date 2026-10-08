"""Notification inbox keyboard, responsive and accessibility checks."""

import os
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.database import database_transaction
from app.notification_center import add_notification
from tests.test_reference_client import QuietHandler
from tests.test_social_home_browser import check_accessibility


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Browser tests are opt-in.",
)
@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_inbox_preferences_and_accessibility(app, users, width):
    from playwright.sync_api import expect, sync_playwright

    with app.app_context(), database_transaction():
        add_notification(
            users[0],
            "social",
            "New friend request",
            "Alex sent you a friend request. "
            "Visit People to accept or decline.",
        )
        add_notification(
            users[0],
            "sources",
            "A connected source needs attention",
            "An automatic sync could not finish. Open Import & sync "
            "to review the connection and retry.",
        )
    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    artifacts = Path(".venv/browser-review")
    artifacts.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={"width": width, "height": 960},
                reduced_motion="reduce",
            )
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/login")
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            bell = page.get_by_role(
                "link", name="Notifications, 2 unread", exact=True
            )
            expect(bell).to_be_visible()
            bell.focus()
            page.keyboard.press("Enter")
            expect(
                page.get_by_role("heading", name="Notifications", exact=True)
            ).to_be_visible()
            expect(page.get_by_role("article")).to_have_count(2)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            check_accessibility(page)
            page.screenshot(
                path=str(artifacts / f"notification-inbox-{width}.png"),
                full_page=True,
            )
            page.get_by_role(
                "button", name="Mark New friend request as read", exact=True
            ).click()
            expect(
                page.get_by_role(
                    "link", name="Notifications, 1 unread", exact=True
                )
            ).to_be_visible()
            page.get_by_role(
                "navigation", name="Notification filters"
            ).get_by_role("link", name="Unread").click()
            expect(page.get_by_role("article")).to_have_count(1)
            page.get_by_role(
                "button", name="Mark all as read", exact=True
            ).click()
            expect(
                page.get_by_role(
                    "link", name="Notifications, 0 unread", exact=True
                )
            ).to_be_visible()
            page.get_by_role(
                "link", name="Notification settings", exact=True
            ).last.click()
            expect(
                page.get_by_role(
                    "heading", name="Notification settings", exact=True
                )
            ).to_be_visible()
            for category in (
                "People",
                "Follow-ups",
                "Import & sync",
                "Daily application reminder",
            ):
                expect(
                    page.get_by_label(f"Email: {category}", exact=True)
                ).not_to_be_checked()
            check_accessibility(page)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(artifacts / f"notification-settings-{width}.png"),
                full_page=True,
            )
            page.get_by_label("Email: People", exact=True).check()
            page.get_by_label("In app: Import & sync", exact=True).uncheck()
            page.get_by_role(
                "button", name="Save notifications", exact=True
            ).click()
            expect(
                page.get_by_label("Email: People", exact=True)
            ).to_be_checked()
            expect(
                page.get_by_label("In app: Import & sync", exact=True)
            ).not_to_be_checked()
            page.get_by_role(
                "link", name="Back to notifications", exact=True
            ).click()
            page.get_by_role(
                "button", name="Dismiss New friend request", exact=True
            ).click()
            expect(page.get_by_role("article")).to_have_count(1)
            page.get_by_role(
                "button", name="Open Import & sync:", exact=False
            ).click()
            expect(page).to_have_url(origin + "/imports")
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
