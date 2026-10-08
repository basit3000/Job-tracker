"""Desktop/mobile setup and repeat sync through a real local Flask server."""

import io
import os
import threading
from pathlib import Path

import pytest
import requests
from werkzeug.serving import make_server

from app.models import JobApplication

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 to run Chromium source flows.",
)

DATA = (
    b"preamble\nignore,ID,Role,Company,Stage,Notes\n"
    b"ignore,job-1,Engineer,Example,Applied,Source note\n"
    b"ignore,job-2,Developer,Example,Submitted,Source note\n"
)


@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1440, "height": 1000},
        {"width": 390, "height": 844},
    ],
)
def test_select_range_map_unique_id_and_repeat_sync(
    app, users, monkeypatch, viewport
):
    from playwright.sync_api import expect, sync_playwright

    data = {"body": DATA}

    def get(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.raw = io.BytesIO(data["body"])
        return response

    monkeypatch.setattr(requests, "get", get)
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    screenshots = Path(".venv/browser-review")
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport=viewport)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url + "/login")
            page.get_by_label("Email").fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(url + "/sources")
            page.get_by_role("link", name="Connect a source").click()
            expect(page.get_by_label("Import from", exact=True)).to_have_value(
                "google"
            )
            expect(page.get_by_label("Import behavior")).to_have_value("sync")
            page.get_by_label("Connection name").fill("Fictional sheet sync")
            page.get_by_label("Google Sheets link").fill(
                "https://docs.google.com/spreadsheets/d/fictionalSheet12345/edit#gid=42"
            )
            page.get_by_label("Cell range (optional)").fill("B2:F4")
            page.get_by_role("button", name="Connect and review").click()
            page.get_by_label(
                "How to identify the same application on later syncs"
            ).select_option("0")
            page.get_by_role(
                "button", name="Preview import", exact=True
            ).click()
            page.get_by_role("heading", name="Review source sync").wait_for()
            assert page.get_by_text("Create", exact=True).count() == 2
            page.get_by_role("button", name="Confirm sync", exact=True).click()
            page.get_by_role("heading", name="Sync complete").wait_for()
            data["body"] = DATA.replace(b"Engineer", b"Senior engineer")
            page.goto(url + "/sources")
            page.get_by_role("button", name="Sync now", exact=True).click()
            page.get_by_role("heading", name="Review source sync").wait_for()
            assert page.get_by_text("Update", exact=True).count() == 1
            assert page.get_by_text("Senior engineer", exact=True).count() == 1
            page.screenshot(
                path=str(screenshots / f"source-sync-{viewport['width']}.png"),
                full_page=True,
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.get_by_role("button", name="Confirm sync", exact=True).click()
            page.get_by_role("heading", name="Sync complete").wait_for()
            with app.app_context():
                assert JobApplication.for_user(users[0]).count() == 2
                assert (
                    JobApplication.query.filter_by(
                        job_title="Senior engineer"
                    ).count()
                    == 1
                )
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
