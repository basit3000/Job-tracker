"""Home discovery, friend consent, saving and keyboard access in Chromium."""

import os
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import User
from tests.test_reference_client import QuietHandler
from tests.test_social_home import feed_people as home_people

feed_people = home_people


def check_accessibility(page):
    """Run an optional local axe-core bundle; no runtime CDN dependency."""
    script = os.environ.get("AXE_CORE_SCRIPT")
    if not script:
        return
    page.evaluate(Path(script).read_text(encoding="utf-8"))
    violations = page.evaluate("""async () => {
      const results = await axe.run(document, {
        runOnly: {
          type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']
        }
      });
      return results.violations.map(v => ({
        id: v.id, impact: v.impact,
        nodes: v.nodes.map(n => ({
          target: n.target, summary: n.failureSummary
        }))
      }));
    }""")
    assert violations == []


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and install Chromium.",
)
@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_social_home_discovery_and_accessibility(
    app, users, feed_people, width
):
    from playwright.sync_api import expect, sync_playwright

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
            expect(page).to_have_url(origin + "/")
            expect(
                page.get_by_role("heading", name="Home", exact=True)
            ).to_be_visible()
            expect(page.get_by_role("article")).to_have_count(2)
            expect(
                page.get_by_role("heading", name="pending role")
            ).to_have_count(0)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(artifacts / f"social-home-{width}.png"),
                full_page=True,
            )
            check_accessibility(page)
            page.reload()
            page.keyboard.press("Tab")
            expect(
                page.get_by_role("link", name="Skip to content")
            ).to_be_focused()
            page.keyboard.press("Enter")
            expect(page.locator("#main-content")).to_be_focused()
            feeds = page.get_by_role("navigation", name="Community feeds")
            friends = feeds.get_by_role("link", name="Friends", exact=True)
            friends.focus()
            assert (
                friends.evaluate("el => getComputedStyle(el).outlineStyle")
                == "solid"
            )
            page.keyboard.press("Enter")
            expect(friends).to_have_attribute("aria-current", "page")
            expect(page.get_by_role("article")).to_have_count(1)
            page.get_by_role(
                "button", name="Accept friend request from pending"
            ).click()
            expect(page).to_have_url(origin + "/")
            expect(
                page.get_by_role("heading", name="pending role")
            ).to_be_visible()
            feeds.get_by_role("link", name="Career wins").click()
            expect(page.get_by_role("article")).to_have_count(1)
            page.get_by_label("Search roles, companies, or people").fill(
                "missing role"
            )
            page.get_by_role("button", name="Search", exact=True).click()
            expect(
                page.get_by_role("heading", name="No matching applications")
            ).to_be_visible()
            page.get_by_role(
                "link", name="Clear search", exact=True
            ).first.click()
            expect(page.get_by_role("article")).to_have_count(1)
            page.get_by_role(
                "button",
                name="Save public role at Example Labs to my shortlist",
            ).click()
            expect(page.get_by_text("Shortlisted", exact=True)).to_be_visible()
            expect(page.get_by_text("PRIVATE_NOTE_SENTINEL")).to_have_count(0)
            page.get_by_role(
                "navigation", name="Application views"
            ).get_by_role("link", name="Insights", exact=True).click()
            expect(
                page.get_by_role("heading", name="My insights")
            ).to_be_visible()
            check_accessibility(page)
            page.goto(origin + "/community")
            expect(
                page.get_by_role("heading", name="People", exact=True)
            ).to_be_visible()
            expect(page).to_have_title("People - Job Tracker")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(
                path=str(artifacts / f"people-{width}.png"), full_page=True
            )
            check_accessibility(page)
            page.goto(origin + "/community/settings")
            page.get_by_label("Username", exact=True).fill("invalid handle")
            page.get_by_role("button", name="Save profile", exact=True).click()
            expect(
                page.get_by_label("Username", exact=True)
            ).to_have_attribute("aria-invalid", "true")
            check_accessibility(page)
            with app.app_context():
                db.session.get(User, feed_people["public"]).share_jobs = False
                db.session.commit()
            page.goto(origin + "/?feed=wins")
            expect(
                page.get_by_role("heading", name="public role")
            ).to_have_count(0)
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
