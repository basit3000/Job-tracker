"""Application factory and extension setup."""

import os
from datetime import datetime, timezone

from flask import Flask, request, url_for

from app.cli import register_cli
from app.errors import register_error_handlers
from app.extensions import (
    csrf,
    db,
    init_google_oauth,
    limiter,
    login_manager,
    migrate,
)
from app.security import register_security_headers
from app.uploads import resume_upload_help


def create_app(config_object="config.Config"):
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_object)

    secret_key = app.config.get("SECRET_KEY")
    if not isinstance(secret_key, (str, bytes)) or len(secret_key) < 32:
        raise ValueError(
            "Set SECRET_KEY to a private random value "
            "of at least 32 characters."
        )

    app.config["UPLOAD_FOLDER"] = os.path.abspath(app.config["UPLOAD_FOLDER"])
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    init_google_oauth(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "warning"

    from app.exports import exports
    from app.models import User, status_slug
    from app.routes.api import api
    from app.routes.auth import auth, main
    from app.routes.google_auth import google_auth
    from app.routes.integrations import integrations
    from app.routes.jobs import jobs

    login_manager.user_loader(User.from_session_id)
    app.jinja_env.filters["status_slug"] = status_slug
    from app.contracts import iso

    app.jinja_env.filters["utc_timestamp"] = iso
    app.jinja_env.globals["pagination_url"] = pagination_url
    app.register_blueprint(auth)
    app.register_blueprint(google_auth)
    app.register_blueprint(main)
    app.register_blueprint(jobs)
    app.register_blueprint(api)
    app.register_blueprint(integrations)
    app.register_blueprint(exports)
    register_cli(app)

    register_error_handlers(app)
    register_security_headers(app)

    @app.context_processor
    def inject_globals():
        return {
            "current_year": datetime.now(timezone.utc).year,
            "resume_upload_help": resume_upload_help(),
            "pagination_url": pagination_url,
        }

    return app


def pagination_url(page):
    filters = {
        key: request.args[key]
        for key in ("q", "status", "sort", "company", "board", "due")
        if key in request.args
    }
    return url_for(request.endpoint, page=page, **filters)
