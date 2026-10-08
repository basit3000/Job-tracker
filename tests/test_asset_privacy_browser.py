"""Pages load their fonts, styles, and scripts without third-party requests."""

import os
import threading
from urllib.parse import urlsplit

import pytest
from werkzeug.serving import make_server

from tests.test_reference_client import QuietHandler


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and install Chromium.",
)
def test_page_assets_stay_on_the_tracker_origin(app, users, job):
    from playwright.sync_api import expect, sync_playwright

    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    external_requests, failed_assets, errors = [], [], []

    def capture_request(request):
        if urlsplit(request.url).netloc != urlsplit(origin).netloc:
            external_requests.append(request.url)

    def capture_response(response):
        if "/static/" in response.url and response.status >= 400:
            failed_assets.append(response.url)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", capture_request)
            page.on("response", capture_response)
            page.goto(origin + "/login")
            page.get_by_label("Email", exact=True).fill("owner@example.com")
            page.get_by_label("Password", exact=True).fill("correct-password")
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page).to_have_url(origin + "/dashboard")
            for path in ("/dashboard", "/community", f"/jobs/{job}"):
                page.goto(origin + path)
                page.evaluate("document.fonts.ready")
                assert page.evaluate(
                    "Array.from(document.fonts).some(font => "
                    "font.family === 'Inter' && font.status === 'loaded')"
                )
                assert page.evaluate("typeof window.bootstrap === 'object'")
            assert not external_requests
            assert not failed_assets
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
