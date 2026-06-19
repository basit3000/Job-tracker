import os

import click
from flask import Flask, render_template

from app.extensions import db, login_manager, migrate, csrf


def create_app(config_object="config.Config"):
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_object)

    # Make sure the upload directory exists before any request tries to use it.
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "warning"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.routes.auth import auth, main
    from app.routes.jobs import jobs

    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(jobs)

    register_error_handlers(app)
    register_context_processors(app)
    register_cli(app)

    return app


def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/error.html", code=403, message="You don't have access to that page."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/error.html", code=404, message="That page could not be found."), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template("errors/error.html", code=413, message="That file is too large (max 5 MB)."), 413

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/error.html", code=500, message="Something went wrong on our end."), 500


def register_context_processors(app):
    from datetime import datetime, timezone

    @app.context_processor
    def inject_globals():
        return {"current_year": datetime.now(timezone.utc).year}


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create database tables (handy for a fresh SQLite setup)."""
        db.create_all()
        click.echo("Initialised the database.")
