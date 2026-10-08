"""Public landing page and the signed-in entry point."""

from flask import Blueprint, render_template, request
from flask_login import current_user

from app.social_home import FEEDS, home_context, shared_feed

main = Blueprint("main", __name__)


@main.get("/")
def home():
    if current_user.is_authenticated:
        feed = request.args.get("feed", "discover")
        if feed not in FEEDS:
            feed = "discover"
        search = request.args.get("q", "").strip()[:80]
        return render_template(
            "community/home.html",
            **home_context(current_user),
            feed=feed,
            feeds=FEEDS,
            search=search,
            pagination=shared_feed(
                current_user.id,
                feed=feed,
                search=search,
                page=max(1, request.args.get("page", 1, type=int)),
            ),
        )
    return render_template("home.html")
