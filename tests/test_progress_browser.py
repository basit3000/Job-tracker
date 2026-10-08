"""Populated charts and reminder settings on desktop and mobile."""

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import JobApplication
from tests.test_reference_client import QuietHandler


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Browser tests are opt-in.",
)
@pytest.mark.parametrize("width", [1440, 390, 320])
def test_progress_and_notification_preferences(app, users, width):
    from playwright.sync_api import expect, sync_playwright

    today = datetime.now(timezone.utc).date()
    with app.app_context():
        for offset in range(24):
            for index in range(offset % 4 + 1):
                db.session.add(
                    JobApplication(
                        user_id=users[0],
                        company="Fictional Labs",
                        job_title=f"Engineer {offset}-{index}",
                        status="applied",
                        applied_on=today - timedelta(days=offset),
                    )
                )
        db.session.commit()
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
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(origin + "/dashboard")
            expect(
                page.get_by_role("heading", name="Applications over time")
            ).to_be_visible()
            expect(
                page.get_by_role("heading", name="24-day streak", exact=False)
            ).to_be_visible()
            expect(page.locator(".daily-chart-column")).to_have_count(28)
            expect(
                page.locator(".calendar-week .calendar-cell")
            ).to_have_count(84)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(artifacts / f"progress-{width}.png"), full_page=True
            )
            page.get_by_text("View daily totals", exact=True).click()
            expect(
                page.get_by_role("cell", name=today.isoformat(), exact=True)
            ).to_be_visible()
            page.get_by_role("link", name="Set a reminder", exact=True).click()
            checkbox = page.get_by_label(
                "Email: Daily application reminder", exact=True
            )
            expect(checkbox).not_to_be_checked()
            checkbox.check()
            page.get_by_label("Your time zone").select_option("Europe/Berlin")
            page.get_by_label("Remind me at").select_option("21")
            page.get_by_role("button", name="Save notifications").click()
            expect(checkbox).to_be_checked()
            expect(page.get_by_label("Your time zone")).to_have_value(
                "Europe/Berlin"
            )
            expect(page.get_by_label("Remind me at")).to_have_value("21")
            expect(
                page.get_by_text(
                    "Email delivery is not configured", exact=False
                )
            ).to_be_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(artifacts / f"notifications-{width}.png"),
                full_page=True,
            )
            checkbox.uncheck()
            page.get_by_role("button", name="Save notifications").click()
            expect(checkbox).not_to_be_checked()
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
