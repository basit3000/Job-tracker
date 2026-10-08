"""Opt-in desktop/mobile browser flows with disposable fictional data."""

import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from werkzeug.serving import make_server

from tests.google_provider import GOOGLE_CONFIG, mock_google_transport
from tests.test_reference_client import QuietHandler


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and install Chromium.",
)
@pytest.mark.parametrize(
    "viewport",
    [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}],
    ids=["desktop", "mobile"],
)
def test_main_browser_flows(app, users, tmp_path, viewport):
    from playwright.sync_api import expect, sync_playwright

    app.config["PUBLIC_SIGNUP_ENABLED"] = False
    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    artifacts = (
        Path(__file__).resolve().parents[1] / ".venv" / "browser-review"
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=viewport,
                is_mobile=viewport["width"] < 600,
                has_touch=viewport["width"] < 600,
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/login")
            expect(page.get_by_role("link", name="Create one")).to_have_count(
                0
            )
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page).to_have_url(origin + "/dashboard")
            page.get_by_role(
                "link", name="Add application", exact=True
            ).click()
            page.get_by_label("Job Title", exact=True).fill(
                "Fictional Platform Engineer"
            )
            page.get_by_label("Company", exact=True).fill("Example Labs")
            page.get_by_label("Status", exact=True).select_option("applied")
            page.get_by_label("Job board / source", exact=True).fill(
                "Example board"
            )
            page.get_by_label("Follow-up date", exact=True).fill("2026-12-01")
            page.get_by_label("Contact email", exact=True).fill(
                "recruiter@example.com"
            )
            page.get_by_label("Notes", exact=True).fill(
                "Fictional private note"
            )
            resume = tmp_path / "fictional.pdf"
            resume.write_bytes(b"%PDF-1.4\nFictional resume fixture")
            page.get_by_label("Resume", exact=True).set_input_files(resume)
            page.get_by_role("button", name="Save", exact=True).click()
            expect(page).to_have_url(re.compile(r"/jobs/\d+$"))
            expect(page.get_by_text("Unknown", exact=True)).to_be_visible()
            expect(
                page.get_by_text("Fictional private note", exact=True)
            ).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role("link", name="Download", exact=True).click()
            assert (
                "Fictional resume fixture"
                in Path(download.value.path()).read_text()
            )
            detail = page.url
            page.get_by_role("link", name="Edit", exact=True).click()
            page.get_by_label("Application date", exact=True).fill(
                "2026-10-06"
            )
            page.get_by_label("Status", exact=True).select_option(
                "interviewing"
            )
            page.get_by_role("button", name="Save", exact=True).click()
            expect(
                page.get_by_text("Applied → Interviewing", exact=False)
            ).to_be_visible()
            for path, heading in (
                ("/dashboard", "Overview"),
                ("/jobs", "Applications"),
                ("/board", "Status board"),
                ("/follow-ups?due=upcoming", "Follow-ups"),
                ("/integrations", "Job Scout connection"),
            ):
                page.goto(origin + path)
                expect(
                    page.get_by_role("heading", name=heading, exact=True)
                ).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                filename = (
                    f"{viewport['width']}-{path.split('?')[0].strip('/')}.png"
                )
                page.screenshot(
                    path=str(artifacts / filename),
                    full_page=True,
                )
            page.goto(origin + "/exports")
            page.get_by_label("note (private detail)").check()
            with page.expect_download() as exported:
                page.get_by_role("button", name="Download JSON").click()
            payload = json.loads(Path(exported.value.path()).read_text())
            assert (
                payload["applications"][0]["note"] == "Fictional private note"
            )
            page.goto(detail)
            page.once("dialog", lambda dialog: dialog.accept())
            page.get_by_role("button", name="Delete", exact=True).click()
            expect(page).to_have_url(origin + "/jobs")
            expect(
                page.get_by_text("No job applications yet.")
            ).to_be_visible()
            if viewport["width"] < 600:
                page.locator(".navbar-toggler").click()
            else:
                page.get_by_role("button", name="Account", exact=True).click()
            page.get_by_role("button", name="Log out", exact=True).click()
            expect(page).to_have_url(origin + "/login")
            assert errors == []
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and install Chromium.",
)
@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
def test_public_registration_and_google_browser_flows(
    app_factory,
    monkeypatch,
    width,
):
    from playwright.sync_api import expect, sync_playwright

    provider = mock_google_transport(monkeypatch)
    app = app_factory(**GOOGLE_CONFIG)
    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    origin = f"http://localhost:{server.server_port}"
    app.config["GOOGLE_REDIRECT_URI"] = origin + "/auth/google/callback"
    provider.redirect_uri = app.config["GOOGLE_REDIRECT_URI"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    identity = {"email": "public-user@example.com", "sub": "public-google-id"}
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": width, "height": 1000},
                is_mobile=width < 600,
                has_touch=width < 600,
            )
            page.on("pageerror", lambda error: errors.append(str(error)))

            def google_authorization(route):
                # Routing matches the first request in a redirect chain.
                # Run the real CSRF-protected start, then simulate consent
                # by replacing only the browser's Google navigation.
                response = route.fetch(max_redirects=0)
                authorization = response.headers["location"]
                assert (
                    urlsplit(authorization).hostname == "accounts.google.com"
                )
                params = parse_qs(urlsplit(authorization).query)
                code = provider.issue(
                    params["nonce"][0],
                    code_challenge=params["code_challenge"][0],
                    **identity,
                )
                callback = (
                    origin
                    + "/auth/google/callback?"
                    + urlencode(
                        {
                            "state": params["state"][0],
                            "code": code,
                        }
                    )
                )
                route.fulfill(
                    response=response,
                    headers={**response.headers, "location": callback},
                )

            page.route(
                origin + "/auth/google",
                google_authorization,
            )

            def logout():
                if width < 600:
                    page.locator(".navbar-toggler").click()
                else:
                    page.get_by_role(
                        "button", name="Account", exact=True
                    ).click()
                page.get_by_role("button", name="Log out", exact=True).click()
                expect(page).to_have_url(origin + "/login")

            page.goto(origin + "/register")
            expect(
                page.get_by_role("button", name="Continue with Google")
            ).to_be_visible()
            page.get_by_label("Email", exact=True).fill(identity["email"])
            page.get_by_label("Password", exact=True).fill(
                "fictional-password"
            )
            page.get_by_label("Confirm Password", exact=True).fill(
                "fictional-password"
            )
            page.get_by_role(
                "button", name="Create account", exact=True
            ).click()
            expect(page).to_have_url(origin + "/login")
            page.get_by_label("Email", exact=True).fill(identity["email"])
            page.get_by_label("Password", exact=True).fill(
                "fictional-password"
            )
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page).to_have_url(origin + "/dashboard")
            page.goto(origin + "/account")
            page.get_by_label("Current password", exact=True).fill(
                "fictional-password"
            )
            page.get_by_role(
                "button", name="Connect Google", exact=True
            ).click()
            expect(
                page.get_by_text("Google is connected.", exact=False)
            ).to_be_visible()
            expect(page).to_have_url(origin + "/account")
            logout()
            page.get_by_role("button", name="Continue with Google").click()
            expect(page).to_have_url(origin + "/dashboard")
            logout()
            identity.update(
                email="google-only@example.com", sub="google-only-id"
            )
            page.get_by_role("link", name="Create one", exact=True).click()
            page.get_by_role("button", name="Continue with Google").click()
            expect(page).to_have_url(origin + "/dashboard")
            page.goto(origin + "/account")
            expect(
                page.get_by_text("Use Google to sign in", exact=False)
            ).to_be_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
