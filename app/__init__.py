"""Application factory and extension setup."""

import os
from datetime import datetime, timezone

from flask import Flask, request, url_for

from app.cli import register_cli
from app.deployment import DeploymentConfigurationError, configure_deployment
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
    configure_deployment(app)
    _configure_storage(app)
    _initialize_extensions(app)
    _register_blueprints(app)
    _configure_templates(app)
    register_cli(app)
    register_error_handlers(app)
    register_security_headers(app)
    return app


def _configure_storage(app):
    secret_key = app.config.get("SECRET_KEY")
    if not isinstance(secret_key, (str, bytes)) or len(secret_key) < 32:
        raise DeploymentConfigurationError(
            "Set SECRET_KEY to a private random value "
            "of at least 32 characters."
        )

    app.config["UPLOAD_FOLDER"] = os.path.abspath(app.config["UPLOAD_FOLDER"])
    if app.config["UPLOAD_STORAGE"] == "filesystem":
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def _initialize_extensions(app):
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    init_google_oauth(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "warning"

    from app.models import User

    login_manager.user_loader(User.from_session_id)


def _register_blueprints(app):
    from app.exports import exports
    from app.routes.api import api
    from app.routes.auth import auth
    from app.routes.community import community
    from app.routes.google_auth import google_auth
    from app.routes.imports import imports
    from app.routes.integrations import integrations
    from app.routes.jobs import jobs
    from app.routes.main import main
    from app.routes.notifications import notifications
    from app.routes.operations import operations
    from app.routes.sources import sources

    for blueprint in (
        auth,
        google_auth,
        main,
        jobs,
        notifications,
        community,
        api,
        integrations,
        exports,
        imports,
        sources,
        operations,
    ):
        app.register_blueprint(blueprint)


def _configure_templates(app):
    from app.contracts import iso
    from app.models import status_slug

    app.jinja_env.filters.update(status_slug=status_slug, utc_timestamp=iso)
    app.jinja_env.globals["pagination_url"] = pagination_url

    @app.context_processor
    def inject_globals():
        from flask_login import current_user

        from app.notification_center import unread_count

        return {
            "unread_notifications": unread_count(current_user.id)
            if current_user.is_authenticated
            else 0,
            "current_year": datetime.now(timezone.utc).year,
            "resume_upload_help": resume_upload_help(),
            "pagination_url": pagination_url,
        }


def pagination_url(page):
    filters = {
        key: request.args[key]
        for key in ("q", "status", "sort", "company", "board", "due")
        if key in request.args
    }
    return url_for(request.endpoint, page=page, **filters)
