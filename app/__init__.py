"""Application factory and extension setup."""

import os
from datetime import datetime, timezone

from flask import Flask

from app.errors import register_error_handlers
from app.extensions import csrf, db, limiter, login_manager, migrate
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

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "warning"

    from app.models import User, status_slug
    from app.routes.auth import auth, main
    from app.routes.jobs import jobs

    login_manager.user_loader(User.from_session_id)
    app.jinja_env.filters["status_slug"] = status_slug
    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(jobs)

    register_error_handlers(app)
    register_security_headers(app)

    @app.context_processor
    def inject_globals():
        return {
            "current_year": datetime.now(timezone.utc).year,
            "resume_upload_help": resume_upload_help(),
        }

    return app
