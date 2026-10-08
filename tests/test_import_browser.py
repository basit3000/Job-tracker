"""Real desktop/mobile import preview and confirmation with fictional data."""

import os
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from tests.test_reference_client import QuietHandler


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Opt-in Chromium checks.",
)
@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
def test_import_browser_flow(app, users, width):
    from playwright.sync_api import expect, sync_playwright

    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/login")
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(origin + "/imports")
            expect(
                page.locator('#source option[value="google"]')
            ).to_have_count(1)
            page.get_by_label("Import from", exact=True).select_option(
                "google"
            )
            expect(page.get_by_label("Google Sheets link")).to_be_visible()
            expect(page.get_by_label("Import behavior")).to_have_value("once")
            expect(page.get_by_label("Connection name")).to_be_hidden()
            page.get_by_label("Import behavior").select_option("sync")
            expect(page.get_by_label("Connection name")).to_be_visible()
            expect(page.get_by_label("Connection name")).to_have_attribute(
                "required", ""
            )
            expect(
                page.get_by_role("button", name="Connect and review")
            ).to_be_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            folder = (
                Path(__file__).resolve().parents[1]
                / ".venv"
                / "browser-review"
            )
            folder.mkdir(exist_ok=True)
            page.screenshot(
                path=str(folder / f"import-setup-{width}.png"), full_page=True
            )
            page.get_by_label("Import from", exact=True).select_option("paste")
            expect(page.get_by_label("Import behavior")).to_be_disabled()
            expect(page.get_by_label("Connection name")).to_be_disabled()
            page.get_by_label("Paste table rows", exact=True).fill(
                "Role\tEmployer\tApplied on\tStage\n"
                "Engineer\tExample\t06/10/2026\tWaiting for recruiter\n"
                "Engineer\tExample\t06/10/2026\tWaiting for recruiter\n"
                "Designer\tExample\t\tSubmitted\n"
                "Invalid row\t\t\tSubmitted"
            )
            page.get_by_role("button", name="Read source", exact=True).click()
            expect(
                page.get_by_role("heading", name="Match your columns")
            ).to_be_visible()
            expect(page.locator("#column_0")).to_have_value("title")
            page.get_by_label("Numeric dates", exact=True).select_option("dmy")
            page.get_by_label(
                "Your status: Waiting for recruiter", exact=True
            ).select_option("applied")
            page.get_by_label(
                "Skip invalid rows and import the valid rows", exact=True
            ).check()
            page.get_by_role(
                "button", name="Preview import", exact=True
            ).click()
            expect(
                page.get_by_role("heading", name="Review your import")
            ).to_be_visible()
            expect(
                page.get_by_role(
                    "button", name="Import 2 applications", exact=True
                )
            ).to_be_enabled()
            expect(
                page.get_by_text("Skip duplicate", exact=True)
            ).to_be_visible()
            expect(page.get_by_text("Unknown", exact=True)).to_have_count(2)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(folder / f"import-review-{width}.png"), full_page=True
            )
            page.get_by_role(
                "button", name="Import 2 applications", exact=True
            ).click()
            expect(
                page.get_by_role("heading", name="Import complete")
            ).to_be_visible()
            expect(
                page.get_by_text("Imported 2 applications.", exact=False)
            ).to_be_visible()
            page.get_by_role(
                "link", name="View applications", exact=True
            ).click()
            expect(
                page.get_by_role("link", name="Engineer", exact=True)
            ).to_be_visible()
            expect(
                page.get_by_role("link", name="Designer", exact=True)
            ).to_be_visible()
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
