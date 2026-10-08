"""Desktop/mobile community journeys on disposable fictional databases."""

import os
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import User
from tests.test_community import shared_record
from tests.test_reference_client import QuietHandler


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and install Chromium.",
)
@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
def test_community_browser_journey(app, users, width):
    from playwright.sync_api import expect, sync_playwright

    with app.app_context():
        person = db.session.get(User, users[1])
        person.handle = "bob"
        person.display_name = "Bob Example"
        person.share_jobs = True
        db.session.commit()
    shared_record(app, users[1])
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
            context = browser.new_context(
                viewport={"width": width, "height": 1000}
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/login")
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(
                page.get_by_text("Your progress", exact=True)
            ).to_be_visible()
            page.goto(origin + "/community/settings")
            page.get_by_label("Username", exact=True).fill("alice")
            page.get_by_label("Display name", exact=True).fill("Alice Example")
            page.get_by_label("Daily application goal", exact=True).fill("6")
            page.get_by_role("button", name="Save profile", exact=True).click()
            expect(
                page.get_by_role("heading", name="Alice Example", exact=True)
            ).to_be_visible()
            page.goto(origin + "/community/u/bob")
            expect(
                page.get_by_role(
                    "heading", name="A private profile", exact=True
                )
            ).to_be_visible()
            page.get_by_role("button", name="Add friend", exact=True).click()
            expect(
                page.get_by_text("Request sent", exact=True)
            ).to_be_visible()
            other_context = browser.new_context(
                viewport={"width": width, "height": 1000}
            )
            other = other_context.new_page()
            other.goto(origin + "/login")
            other.get_by_label("Email", exact=True).fill("other@example.com")
            other.get_by_label("Password", exact=True).fill("other-password")
            other.get_by_role("button", name="Log in", exact=True).click()
            other.goto(origin + "/community")
            other.get_by_role("button", name="Accept", exact=True).click()
            page.reload()
            expect(
                page.get_by_text("Shared Example Labs", exact=True)
            ).to_be_visible()
            page.screenshot(
                path=str(artifacts / f"community-profile-{width}.png"),
                full_page=True,
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.get_by_role(
                "button", name="Save to my shortlist", exact=True
            ).click()
            expect(page.get_by_text("Shortlisted", exact=True)).to_be_visible()
            expect(
                page.get_by_text("PRIVATE_NOTE_SENTINEL", exact=True)
            ).to_have_count(0)
            page.goto(origin + "/community")
            expect(
                page.get_by_role("link", name="Bob Example", exact=True)
            ).to_have_count(2)
            page.get_by_label("Compare by", exact=True).select_option(
                "best_day"
            )
            page.get_by_role("button", name="Compare", exact=True).click()
            page.screenshot(
                path=str(artifacts / f"community-{width}.png"), full_page=True
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            other.goto(origin + "/community/settings")
            other.get_by_label(
                "Share my applied jobs on my profile", exact=True
            ).uncheck()
            other.get_by_role(
                "button", name="Save profile", exact=True
            ).click()
            page.goto(origin + "/community/u/bob")
            expect(
                page.get_by_text("Shared Example Labs", exact=True)
            ).to_have_count(0)
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
